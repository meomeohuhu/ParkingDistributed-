import cv2
import threading
import tkinter as tk
from tkinter import *
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import requests, time
import uuid

# ✅ LOCAL Gate API (node) — UI gọi vào đây để đúng phân tán
LOCAL_API = "http://172.26.12.152:8000"

# ==========================
# AUTH (Cloud/Local đều dùng)
# ==========================
AUTH_HEADER = {
    "Authorization": "Bearer secret-key"
}

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
# HTTP HELPERS (Local-first + fallback Cloud)
# =======================================================
def http_get_json(local_url: str, cloud_url: str | None = None, params=None, timeout=3):
    """
    Ưu tiên gọi local_url (đúng phân tán).
    Nếu local trả 404/401 hoặc lỗi network -> fallback cloud_url (nếu có).
    """
    # 1) local first
    try:
        r = requests.get(local_url, params=params, headers=AUTH_HEADER, timeout=timeout)
        if r.status_code == 200:
            return True, r.json(), r
        # local có thể không implement route -> 404
        # local có thể chặn auth -> 401
        if cloud_url and r.status_code in (401, 404):
            raise RuntimeError(f"Local {r.status_code}, fallback cloud")
        return False, None, r
    except Exception:
        # 2) fallback cloud
        if not cloud_url:
            return False, None, None
        try:
            r2 = requests.get(cloud_url, params=params, headers=AUTH_HEADER, timeout=timeout)
            if r2.status_code == 200:
                return True, r2.json(), r2
            return False, None, r2
        except Exception:
            return False, None, None


def http_post_json(local_url: str, cloud_url: str | None = None, json=None, timeout=8):
    """
    Ưu tiên local POST, lỗi thì fallback cloud nếu có.
    """
    try:
        r = requests.post(local_url, json=json, headers=AUTH_HEADER, timeout=timeout)
        if r.status_code == 200:
            return True, r.json(), r
        if cloud_url and r.status_code in (401, 404):
            raise RuntimeError(f"Local {r.status_code}, fallback cloud")
        return False, None, r
    except Exception:
        if not cloud_url:
            return False, None, None
        try:
            r2 = requests.post(cloud_url, json=json, headers=AUTH_HEADER, timeout=timeout)
            if r2.status_code == 200:
                return True, r2.json(), r2
            return False, None, r2
        except Exception:
            return False, None, None


def http_post_upload(local_url: str, cloud_url: str | None = None, files=None, data=None, timeout=8):
    """
    Upload best-effort: local trước.
    Nếu local fail mà cloud_url có -> thử cloud.
    """
    try:
        r = requests.post(local_url, files=files, data=data, timeout=timeout)
        if r.status_code == 200:
            return True, r.json(), r
        if cloud_url and r.status_code in (401, 404):
            raise RuntimeError(f"Local {r.status_code}, fallback cloud")
        return False, None, r
    except Exception:
        if not cloud_url:
            return False, None, None
        try:
            r2 = requests.post(cloud_url, files=files, data=data, timeout=timeout)
            if r2.status_code == 200:
                return True, r2.json(), r2
            return False, None, r2
        except Exception:
            return False, None, None


# =======================================================
# OCR 2 DÒNG + VIETQR
# =======================================================
def show_vietqr(parent, plate: str, local_api: str, cloud_api: str):
    """
    ✅ FIX:
    - Lấy fee từ LOCAL trước.
    - Nếu LOCAL /fee không có (404) hoặc 401 -> fallback CLOUD /fee.
    - Nếu fail -> popup lỗi rõ ràng (không "im lặng").
    """
    plate = (plate or "").strip().upper()
    if not plate:
        messagebox.showerror("Lỗi", "Chưa có biển số để tính phí!")
        return False

    ok, data, resp = http_get_json(
        f"{local_api}/fee",
        f"{cloud_api}/fee" if cloud_api else None,
        params={"plate": plate},
        timeout=4
    )

    if not ok or not data:
        if resp is not None:
            messagebox.showerror("Lỗi", f"Không lấy được phí:\n{resp.status_code} {resp.text}")
        else:
            messagebox.showerror("Lỗi", "Không lấy được phí (mất kết nối local & cloud).")
        return False

    try:
        amount = int(data.get("amount", 0))
        trans_id = str(data.get("trans_id", ""))
        if amount <= 0 or not trans_id:
            messagebox.showerror("Lỗi", f"Dữ liệu phí không hợp lệ:\n{data}")
            return False
        content = f"PARK-{trans_id[:8].upper()}"
    except Exception as e:
        messagebox.showerror("Lỗi", f"Lỗi parse phí: {e}\n{data}")
        return False

    bank_code = "MB"
    account_no = "4506120217"
    account_name = "NGUYEN THANH THINH"

    vietqr_img_url = (
        f"https://img.vietqr.io/image/"
        f"{bank_code}-{account_no}-compact2.png"
        f"?amount={amount}"
        f"&addInfo={content}"
        f"&accountName={account_name.replace(' ', '%20')}"
    )

    try:
        resp = requests.get(vietqr_img_url, timeout=6)
        if resp.status_code != 200:
            messagebox.showerror("Lỗi", f"Lỗi tải ảnh QR: {resp.status_code}")
            return False
        path = f"vietqr_{uuid.uuid4().hex[:8]}.png"
        with open(path, "wb") as f:
            f.write(resp.content)
    except Exception as e:
        messagebox.showerror("Lỗi", f"Lỗi tạo QR: {e}")
        return False

    win = tk.Toplevel(parent)
    win.title("Thanh toán VietQR")
    win.geometry("420x520")
    win.resizable(False, False)

    Label(win, text="Quét QR để thanh toán", font=("Arial", 14, "bold")).pack(pady=10)

    qr_img = Image.open(path).resize((360, 360))
    qr_tk = ImageTk.PhotoImage(qr_img)
    lbl = Label(win, image=qr_tk)
    lbl.image = qr_tk
    lbl.pack(pady=10)

    Label(
        win,
        text=f"Số tiền: {amount} VND\nNội dung: {content}",
        font=("Arial", 11)
    ).pack(pady=5)

    paid = {"ok": False}

    def confirm():
        paid["ok"] = True
        win.destroy()

    Button(
        win,
        text="✅ Đã thanh toán",
        font=("Arial", 12, "bold"),
        bg="#27ae60",
        fg="white",
        command=confirm
    ).pack(pady=15)

    win.grab_set()
    win.wait_window()
    return paid["ok"]


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
    def __init__(self, owner, parent, title, cloud_api, local_api, gate_id, shared_cam):
        self.owner = owner
        self.parent = parent
        self.cloud_api = cloud_api
        self.local_api = local_api
        self.gate_id = gate_id
        self.shared_cam = shared_cam
        self.mode = title
        self.running = True
        self.slot_locked = False
        self.plate_locked = False
        self.slot_display_map = {}

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

    def on_user_typing(self, event):
        self.user_typing = True
        self.last_input_time = time.time()

    # =======================================================
    # LOAD SLOTS
    # =======================================================
    def load_slots(self):
        """
        ✅ FIX:
        - Local-first /slots
        - Fallback cloud /slots
        - IN: show free slots + distance if có
        - OUT: show occupied slots
        """
        try:
            mode = "in" if self.mode == "IN" else "out"
            ok, j, resp = http_get_json(
                f"{self.local_api}/slots",
                f"{self.cloud_api}/slots" if self.cloud_api else None,
                params={"gate_id": self.gate_id, "mode": mode},
                timeout=3
            )

            if not ok or not j:
                self.slot_box["values"] = []
                return

            slots = j.get("slots", [])

            if self.mode == "IN":
                free_slots = []
                self.slot_display_map.clear()

                for s in slots:
                    # cloud /slots có occupied, local cũng nên có
                    if bool(s.get("occupied", False)) is True:
                        continue

                    dist = float(s.get("distance", 0))
                    slotid = s.get("slotid")
                    if slotid:
                        free_slots.append((dist, slotid))

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
                used = []
                for s in slots:
                    # nếu local đã filter out = occupied, thì slotid đủ
                    if s.get("slotid"):
                        # nếu cloud trả cả free/used => lọc used
                        if "occupied" in s and not bool(s["occupied"]):
                            continue
                        used.append(s["slotid"])
                self.slot_box["values"] = used

        except Exception as e:
            print("load_slots error:", e)
            self.slot_box["values"] = []

    # =======================================================
    def on_slot_select(self, event):
        self.slot_locked = True
        self.plate_locked = True
        self.user_typing = False

        if self.mode == "IN":
            return

        # OUT: lấy plate theo slot từ local slots, fail thì fallback cloud
        try:
            ok, j, _ = http_get_json(
                f"{self.local_api}/slots",
                f"{self.cloud_api}/slots" if self.cloud_api else None,
                params={"gate_id": self.gate_id, "mode": "all"},
                timeout=3
            )
            if not ok or not j:
                return

            for s in j.get("slots", []):
                if s.get("slotid") == self.slot_var.get() and s.get("plate"):
                    self.plate_var.set(s["plate"])
                    break
        except:
            pass

    # =======================================================
    def suggest_slot(self):
        """
        ✅ FIX:
        - Local-first /suggest_slot
        - Nếu local thiếu route => fallback cloud.
        - Có AUTH_HEADER => không còn 401.
        """
        if self.slot_locked:
            return

        try:
            ok, j, resp = http_get_json(
                f"{self.local_api}/suggest_slot/{self.gate_id}",
                f"{self.cloud_api}/suggest_slot/{self.gate_id}" if self.cloud_api else None,
                params=None,
                timeout=3
            )
            if not ok or not j:
                return

            slot = j.get("slot")
            distance = j.get("distance")

            if slot:
                self.slot_var.set(slot)
                if distance is None:
                    self.suggest_label.config(text=f"🅿 Gợi ý gần nhất: {slot}", fg="#2c3e50")
                else:
                    self.suggest_label.config(
                        text=f"🅿 Gợi ý gần nhất: {slot} | 📏 {float(distance):.2f} m",
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

                texts = OCR.readtext(crop, detail=0)
                plate = "".join(texts).replace(" ", "").replace("-", "").upper()

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                if plate:
                    cv2.putText(frame, plate, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

                if len(plate) >= 4:
                    if not self.plate_locked and not self.user_typing:
                        self.frame.after(0, lambda p=plate: self.plate_var.set(p))

                    if not self.slot_locked and self.mode == "IN":
                        self.frame.after(0, self.suggest_slot)

                    break

            time.sleep(0.3)

    # =======================================================
    # XE VÀO
    # =======================================================
    def vehicle_in(self):
        plate = self.plate_var.get().strip().upper()

        slot_label = self.slot_var.get()
        slot = self.slot_display_map.get(slot_label, slot_label).strip().upper()

        if not plate:
            return messagebox.showerror("Lỗi", "Chưa nhận diện biển số!")
        if not slot:
            return messagebox.showerror("Lỗi", "Chưa chọn chỗ đậu!")

        frame = self.shared_cam.get()
        if frame is None:
            return messagebox.showerror("Lỗi", "Không có ảnh camera!")

        # Best-effort reserve (cloud còn thì tránh tranh chấp)
        try:
            requests.post(
                self.cloud_api + "/reserve_slot",
                json={"gate": self.gate_id, "slot": slot, "ttl": 15},
                headers=AUTH_HEADER,
                timeout=2
            )
        except:
            pass

        ok, jpg = cv2.imencode(".jpg", frame)
        files = {"file": ("in.jpg", jpg.tobytes(), "image/jpeg")}
        data = {"plate": plate, "gate": self.gate_id}

        # Upload local-first, fallback cloud
        img_path = None
        try:
            ok_u, j_u, _ = http_post_upload(
                f"{self.local_api}/upload_image_in",
                f"{self.cloud_api}/upload_image_in" if self.cloud_api else None,
                files=files,
                data=data,
                timeout=8
            )
            if ok_u and j_u:
                img_path = j_u.get("path")
        except Exception as e:
            print("upload_image_in error:", e)

        # Vehicle_in local-first, fallback cloud
        ok2, j2, resp2 = http_post_json(
            f"{self.local_api}/vehicle_in",
            f"{self.cloud_api}/vehicle_in" if self.cloud_api else None,
            json={"plate": plate, "slot": slot, "gate": self.gate_id, "img_in": img_path},
            timeout=8
        )

        if not ok2 or not j2:
            if resp2 is not None:
                return messagebox.showerror("Lỗi", f"Xe vào lỗi:\n{resp2.status_code} {resp2.text}")
            return messagebox.showerror("Lỗi", "Xe vào lỗi (mất kết nối).")

        if not j2.get("ok", False):
            messagebox.showwarning("Thông báo", str(j2))
        else:
            messagebox.showinfo("Thành công", "Xe vào thành công!")

        self.load_slots()
        if hasattr(self, "owner"):
            self.owner.refresh_all_slots()

    # =======================================================
    # XE RA
    # =======================================================
    def vehicle_out(self):
        plate = self.plate_var.get().strip().upper()

        if not plate:
            return messagebox.showerror("Lỗi", "Chưa nhận diện biển số!")

        # ✅ FIX: show_vietqr local-first + fallback cloud
        paid = show_vietqr(self.frame, plate, self.local_api, self.cloud_api)
        if not paid:
            return  # đã có popup lỗi/hoặc chưa xác nhận

        frame = self.shared_cam.get()
        if frame is None:
            return messagebox.showerror("Lỗi", "Không có ảnh camera!")

        ok, jpg = cv2.imencode(".jpg", frame)
        files = {"file": ("out.jpg", jpg.tobytes(), "image/jpeg")}
        data = {"plate": plate, "gate": self.gate_id}

        # Upload local-first, fallback cloud
        img_path = None
        try:
            ok_u, j_u, _ = http_post_upload(
                f"{self.local_api}/upload_image_out",
                f"{self.cloud_api}/upload_image_out" if self.cloud_api else None,
                files=files,
                data=data,
                timeout=8
            )
            if ok_u and j_u:
                img_path = j_u.get("path")
        except Exception as e:
            print("upload_image_out error:", e)
            # vẫn cho xe ra

        # vehicle_out local-first, fallback cloud
        ok2, j2, resp2 = http_post_json(
            f"{self.local_api}/vehicle_out",
            f"{self.cloud_api}/vehicle_out" if self.cloud_api else None,
            json={"plate": plate, "img_out": img_path, "gate": self.gate_id},
            timeout=8
        )

        if not ok2 or not j2:
            if resp2 is not None:
                return messagebox.showerror("Lỗi", f"Xe ra lỗi:\n{resp2.status_code} {resp2.text}")
            return messagebox.showerror("Lỗi", "Xe ra lỗi (mất kết nối).")

        if not j2.get("ok", False):
            messagebox.showwarning("Thông báo", str(j2))
        else:
            messagebox.showinfo("Thành công", "Xe ra thành công!")

        self.load_slots()
        if hasattr(self, "owner"):
            self.owner.refresh_all_slots()


# =======================================================
# SECURITY UI (FULLSCREEN)
# =======================================================
class SecurityUI:
    """
    ✅ FIX quan trọng:
    - Để tránh TypeError do gui_main truyền thiếu/thừa args,
      mình cho local_api là optional.
    => gui_main gọi:
        SecurityUI(self, self.cloud, self.gateid)
      hoặc
        SecurityUI(self, self.cloud, self.gateid, LOCAL_API)
      đều OK.
    """
    def __init__(self, parent, cloud_api, gate_id, local_api=LOCAL_API):
        self.win = tk.Toplevel(parent)
        self.win.title("Security Control Room")
        self.win.state("zoomed")
        self.win.configure(bg="#dfe6e9")

        self.cloud_api = cloud_api
        self.local_api = local_api
        self.gate_id = gate_id

        # ✅ tạo camera trước rồi mới update view
        self.shared_cam = SharedCamera()

        # CLOSE EVENT
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

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

        self.panel_in = CameraPanel(self, container, "IN", self.cloud_api, self.local_api, self.gate_id, self.shared_cam)
        self.panel_out = CameraPanel(self, container, "OUT", self.cloud_api, self.local_api, self.gate_id, self.shared_cam)

        self.panel_in.frame.pack(side="left", expand=True)
        self.panel_out.frame.pack(side="right", expand=True)

        self.active_panel = self.panel_in

        # start live view loop
        self.update_live_view()

    def on_close(self):
        print("🛑 Stopping camera…")
        try:
            self.shared_cam.stop()
        except:
            pass
        self.win.destroy()

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

    def switch_in(self):
        self.active_panel = self.panel_in

    def switch_out(self):
        self.active_panel = self.panel_out

    def refresh_all_slots(self):
        self.panel_in.load_slots()
        self.panel_out.load_slots()
