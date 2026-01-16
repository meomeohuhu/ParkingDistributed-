import cv2
import threading
import tkinter as tk
from tkinter import *
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import requests, time

# YOLO + OCR
from ultralytics import YOLO
import easyocr
import torch
from ultralytics.nn.tasks import DetectionModel
torch.serialization.add_safe_globals([DetectionModel])

MODEL = YOLO("best.pt", verbose=False)
OCR = easyocr.Reader(['en'], gpu=False)

MIN_PLATE_SIZE = 80


# =======================================================
# OCR 2 DÒNG
# =======================================================
def read_plate_two_lines(crop):
    h, w, _ = crop.shape
    if h < 20:
        return ""

    mid = h // 2
    t1 = OCR.readtext(crop[:mid], detail=0)
    t2 = OCR.readtext(crop[mid:], detail=0)

    text = (t1[0] if t1 else "") + (t2[0] if t2 else "")
    return text.replace(" ", "").replace("-", "").upper()


# =======================================================
# SHARED CAMERA – TỰ PHỤC HỒI KHI MẤT KẾT NỐI
# =======================================================
class SharedCamera:
    def __init__(self):
        self.cap = cv2.VideoCapture(0)
        self.frame = None
        self.running = True
        threading.Thread(target=self.update, daemon=True).start()

    def update(self):
        while self.running:
            ret, img = self.cap.read()

            if not ret:
                print("⚠ Camera lost — retry…")
                time.sleep(0.2)
                try:
                    self.cap.release()
                except:
                    pass
                self.cap = cv2.VideoCapture(0)
                continue

            self.frame = img

    def get(self):
        return self.frame

    def stop(self):
        self.running = False
        try:
            if self.cap.isOpened():
                self.cap.release()
        except:
            pass


# =======================================================
# CAMERA PANEL – IN / OUT
# =======================================================
class CameraPanel:
    def __init__(self, owner, parent, title, cloud_api, gate_id, shared_cam):
        self.owner = owner
        self.parent = parent
        self.cloud_api = cloud_api
        self.gate_id = gate_id
        self.shared_cam = shared_cam
        self.mode = title
        self.running = True
        self.slot_locked = False     # đã chọn slot hay chưa
        self.plate_locked = False    # đã khóa biển số hay chưa
        self.slot_display_map = {}   # "S01 (3.2m)" -> "S01"



        self.user_typing = False
        self.last_input_time = time.time()

        # ================= FRAME =================
        self.frame = Frame(parent, bg="#ecf0f1", padx=20, pady=15)

        Label(
            self.frame,
            text=f"CAMERA {self.mode}",
            font=("Arial", 22, "bold"),
            bg="#ecf0f1"
        ).pack(pady=10)

        # ================= GỢI Ý SLOT =================
        self.suggest_label = Label(
            self.frame,
            text="",
            font=("Arial", 13, "italic"),
            fg="#2980b9",
            bg="#ecf0f1"
        )
        self.suggest_label.pack(pady=6)

        # ================= VIDEO =================
        self.video_label = Label(self.frame, bg="black", width=650, height=430)
        self.video_label.pack()

        # ================= BIỂN SỐ =================
        Label(self.frame, text="Biển số:", font=("Arial", 14), bg="#ecf0f1").pack()
        self.plate_var = StringVar()

        entry = Entry(
            self.frame,
            textvariable=self.plate_var,
            font=("Arial", 16),
            width=18,
            justify="center"
        )
        entry.pack(pady=5)
        entry.bind("<Key>", self.on_user_typing)

        # ================= SLOT =================
        Label(self.frame, text="Chỗ đậu:", font=("Arial", 14), bg="#ecf0f1").pack()
        self.slot_var = StringVar()

        self.slot_box = ttk.Combobox(
            self.frame,
            textvariable=self.slot_var,
            font=("Arial", 16),
            width=16,
            state="readonly"
        )
        self.slot_box.pack()
        self.slot_box.bind("<<ComboboxSelected>>", self.on_slot_select)

        # ================= BUTTON =================
        if self.mode == "IN":
            btn_text = "XE VÀO"
            btn_color = "#27ae60"
            action = self.vehicle_in
        else:
            btn_text = "XE RA"
            btn_color = "#c0392b"
            action = self.vehicle_out

        Button(
            self.frame,
            text=btn_text,
            font=("Arial", 18, "bold"),
            bg=btn_color,
            fg="white",
            command=action
        ).pack(pady=12)

        self.load_slots()
        threading.Thread(target=self.yolo_loop, daemon=True).start()



    # =======================================================
    def on_user_typing(self, event):
        self.user_typing = True
        self.last_input_time = time.time()


    # =======================================================
    def load_slots(self):
        try:
            r = requests.get(
                self.cloud_api + "/slots",
                params={"gate_id": self.gate_id},
                headers={"Authorization": "Bearer secret-key"}
            )
            slots = r.json()["slots"]

            if self.mode == "IN":
                free_slots = []
                self.slot_display_map.clear()

                for s in slots:
                    if not s["occupied"]:
                        dist = float(s.get("distance", 9999))
                        free_slots.append((dist, s["slotid"]))

                # ✅ sắp xếp theo khoảng cách (gần → xa)
                free_slots.sort(key=lambda x: x[0])

                values = []
                for dist, slotid in free_slots:
                    label = f"{slotid}  ({dist:.1f} m)"
                    self.slot_display_map[label] = slotid
                    values.append(label)

                self.slot_box["values"] = values
                self.slot_locked = False
                self.plate_locked = False

                if not self.slot_var.get():
                    self.suggest_slot()


            else:
                used = [s["slotid"] for s in slots if s["occupied"]]
                self.slot_box["values"] = used

        except Exception as e:
            print("load_slots error:", e)



    # =======================================================
    def on_slot_select(self, event):
        self.slot_locked = True
        self.plate_locked = True
        self.user_typing = False   # ✅ reset typing


        # XE VÀO: KHÔNG ĐỤNG GÌ ĐẾN BIỂN SỐ
        if self.mode == "IN":
            return

        # XE RA: fill biển số từ DB
        try:
            r = requests.get(
                self.cloud_api + "/slots",
                headers={"Authorization": "Bearer secret-key"}
            )
            for s in r.json()["slots"]:
                if s["slotid"] == self.slot_var.get() and s.get("plate"):
                    self.plate_var.set(s["plate"])
                    break
        except:
            pass


        
    def suggest_slot(self):
        if self.slot_locked:
            return  # ⛔ người dùng đã chọn tay

        try:
            r = requests.get(
                f"{self.cloud_api}/suggest_slot/{self.gate_id}",
                headers={"Authorization": "Bearer secret-key"},
                timeout=3
            )
            j = r.json()

            slot = j.get("slot")
            distance = j.get("distance")

            if slot and distance is not None:
                distance = float(distance)
                self.slot_var.set(slot)
                self.suggest_label.config(
                    text=f"🅿 Gợi ý gần nhất: {slot}  |  📏 {distance:.2f} m từ cổng",
                    fg="#2c3e50"
                )

        except Exception as e:
            print("suggest_slot error:", e)






    # =======================================================
    # YOLO LOOP
    # =======================================================
    def yolo_loop(self):
        while self.running:
            frame = self.shared_cam.get()
            if frame is None:
                time.sleep(0.1)
                continue

            results = MODEL(frame)[0]

            for b in results.boxes:
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                crop = frame[y1:y2, x1:x2]

                # OCR FULL FRAME (không chia 2 dòng)
                texts = OCR.readtext(crop, detail=0)
                plate = "".join(texts).replace(" ", "").replace("-", "").upper()

                # vẽ box để debug
                cv2.rectangle(frame, (x1,y1), (x2,y2), (0,255,0), 2)
                if plate:
                    cv2.putText(frame, plate, (x1, y1-10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2)

                if len(plate) >= 4:
                    if not self.plate_locked and not self.user_typing:
                        self.frame.after(0, lambda p=plate: self.plate_var.set(p))


                    if not self.slot_locked:
                        self.frame.after(0, self.suggest_slot)

                    break


            time.sleep(0.3)




    # =======================================================
    # XE VÀO
    # =======================================================
    def vehicle_in(self):
        plate = self.plate_var.get().strip().upper()
        slot = self.slot_var.get()

        if not plate:
            return messagebox.showerror("Lỗi", "Chưa nhận diện biển số!")
        if not slot:
            return messagebox.showerror("Lỗi", "Chưa chọn chỗ đậu!")

        frame = self.shared_cam.get()
        if frame is None:
            return messagebox.showerror("Lỗi", "Không có ảnh camera!")

        ok, jpg = cv2.imencode(".jpg", frame)
        files = {"file": ("in.jpg", jpg.tobytes(), "image/jpeg")}
        data = {"plate": plate, "gate": self.gate_id}

        # UPLOAD ẢNH QUA LOCAL API → CLOUD
        try:
            r = requests.post(
                "http://localhost:8000/upload_image_in",
                files=files,
                data=data,
                timeout=8
            )
            j = r.json()
        except Exception as e:
            return messagebox.showerror("Lỗi Upload", str(e))

        img_path = j.get("path")
        if not img_path:
            return messagebox.showerror("Lỗi Upload", str(j))

        # GỬI XE VÀO CLOUD
        requests.post(self.cloud_api + "/vehicle_in",
                      json={"plate": plate,
                            "slot": slot,
                            "gate": self.gate_id,
                            "img_in": img_path},
                      headers={"Authorization": "Bearer secret-key"})

        self.load_slots()
        if hasattr(self, "owner"):
            self.owner.refresh_all_slots()

        messagebox.showinfo("Thành công", "Xe vào thành công!")


    # =======================================================
    # XE RA
    # =======================================================
    def vehicle_out(self):
        plate = self.plate_var.get().strip().upper()

        if not plate:
            return messagebox.showerror("Lỗi", "Chưa nhận diện biển số!")

        frame = self.shared_cam.get()
        if frame is None:
            return messagebox.showerror("Lỗi", "Không có ảnh camera!")

        ok, jpg = cv2.imencode(".jpg", frame)
        files = {"file": ("out.jpg", jpg.tobytes(), "image/jpeg")}
        data = {"plate": plate, "gate": self.gate_id}

        # UPLOAD
        try:
            r = requests.post(
                "http://localhost:8000/upload_image_out",
                files=files,
                data=data,
                timeout=8
            )
            j = r.json()
        except Exception as e:
            return messagebox.showerror("Lỗi Upload", str(e))

        img_path = j.get("path")
        if not img_path:
            return messagebox.showerror("Lỗi Upload", str(j))

        # GỬI XE RA CLOUD
        try:
            r2 = requests.post(
                self.cloud_api + "/vehicle_out",
                json={"plate": plate, "img_out": img_path, "gate": self.gate_id},
                headers={"Authorization": "Bearer secret-key"},
                timeout=5
            )
            j2 = r2.json()
        except Exception as e:
            return messagebox.showerror("Lỗi Cloud", str(e))

        if not j2.get("ok"):
            return messagebox.showerror("Lỗi", str(j2))

        self.load_slots()
        if hasattr(self, "owner"):
            self.owner.refresh_all_slots()

        messagebox.showinfo("Thành công", "Xe ra thành công!")


# =======================================================
# SECURITY UI (FULLSCREEN)
# =======================================================
class SecurityUI:
    def __init__(self, parent, cloud_api, gate_id):
        self.win = tk.Toplevel(parent)
        self.win.title("Security Control Room")
        self.win.state("zoomed")
        self.win.configure(bg="#dfe6e9")
        self.update_live_view()


        # CLOSE EVENT
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

        self.shared_cam = SharedCamera()

        menu = Frame(self.win, bg="#dfe6e9")
        menu.pack(fill="x")

        Button(menu, text="🚗 XE VÀO", font=("Arial", 14, "bold"),
               bg="#27ae60", fg="white",
               command=self.switch_in).pack(side="left", padx=10, pady=5)

        Button(menu, text="🚙 XE RA", font=("Arial", 14, "bold"),
               bg="#c0392b", fg="white",
               command=self.switch_out).pack(side="left", pady=5)

        container = Frame(self.win, bg="#dfe6e9")
        container.pack(fill="both", expand=True)

        self.panel_in = CameraPanel(self, container, "IN", cloud_api, gate_id, self.shared_cam)
        self.panel_out = CameraPanel(self, container, "OUT", cloud_api, gate_id, self.shared_cam)

        self.panel_in.frame.pack(side="left", expand=True)
        self.panel_out.frame.pack(side="right", expand=True)

        self.active_panel = self.panel_in

    # =======================================================
    def on_close(self):
        print("🛑 Stopping camera…")
        try:
            self.shared_cam.stop()
        except:
            pass
        self.win.destroy()

    # =======================================================
    def update_live_view(self):
        if not self.win.winfo_exists():
            return

        try:
            frame = self.shared_cam.get()
            if frame is not None:
                show = cv2.resize(frame, (650, 430))
                rgb = cv2.cvtColor(show, cv2.COLOR_BGR2RGB)
                imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))

                label = self.active_panel.video_label
                if label.winfo_exists():
                    label.configure(image=imgtk)
                    label.image = imgtk

        except Exception as e:
            print("LIVE VIEW ERROR:", e)

        self.win.after(30, self.update_live_view)


    # =======================================================
    def switch_in(self):
        self.active_panel = self.panel_in

    def switch_out(self):
        self.active_panel = self.panel_out
    
    def refresh_all_slots(self):
        self.panel_in.load_slots()
        self.panel_out.load_slots()

