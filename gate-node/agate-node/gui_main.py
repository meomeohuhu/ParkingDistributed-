import tkinter as tk
from tkinter import messagebox, simpledialog
import requests, sqlite3
from config import load_config, save_config
from gate_app import DB_PATH
from security_ui import SecurityUI
from gate_ws import GUI_EVENT_QUEUE
from admin_ui import AdminUI

from PIL import Image, ImageTk
import io

# ==========================================================
# MÀU SẮC HỆ THỐNG
# ==========================================================
GREEN = "#27ae60"
GREEN_LIGHT = "#2ecc71"
RED = "#e74c3c"
GRAY = "#34495e"
BG = "#ecf0f1"
BLUE = "#2980b9"
POLL = 5  # seconds auto refresh


# ==========================================================
# Tooltip nâng cấp (có thể chứa text + thumbnail)
# ==========================================================
class Tooltip:
    def __init__(self, canvas):
        self.canvas = canvas
        self.tip_text = None
        self.tip_image = None

    def hide(self):
        if self.tip_text:
            self.canvas.delete(self.tip_text)
            self.tip_text = None
        if self.tip_image:
            self.canvas.delete(self.tip_image)
            self.tip_image = None

    def show_text(self, x, y, text):
        self.hide()
        self.tip_text = self.canvas.create_text(
            x, y - 15,
            text=text,
            fill="black",
            font=("Segoe UI", 11, "bold"),
            anchor="s"
        )

    def show_with_image(self, x, y, text, pil_image):
        self.hide()

        # Render text
        self.tip_text = self.canvas.create_text(
            x, y - 15,
            text=text,
            fill="black",
            font=("Segoe UI", 11, "bold"),
            anchor="s"
        )

        # Render thumbnail
        img = pil_image.resize((120, 90))
        self.thumb = ImageTk.PhotoImage(img)
        self.tip_image = self.canvas.create_image(
            x + 70, y - 60,
            image=self.thumb,
            anchor="nw"
        )


# ==========================================================
# Slot Detail Window
# ==========================================================
class SlotDetailWindow(tk.Toplevel):
    def __init__(self, parent, info, cloud_api):
        super().__init__(parent)
        self.title(f"Chi tiết Slot {info['slotid']}")
        self.geometry("500x420")
        self.configure(bg="white")

        tk.Label(self, text=f"Slot {info['slotid']}",
                 font=("Arial", 22, "bold"),
                 bg="white").pack(pady=10)

        plate = info["plate"]
        tk.Label(self, text=f"Biển số: {plate}",
                 bg="white", font=("Arial", 16)).pack(pady=5)

        tk.Label(self, text=f"Giờ vào: {info['time_in']}",
                 bg="white", font=("Arial", 14)).pack()

        # Ảnh
        img_frame = tk.Frame(self, bg="white")
        img_frame.pack(pady=20)

        # Ảnh xe vào
        try:
            url = f"{cloud_api}/view_image?path={info['img_in']}"
            data = requests.get(url).content
            im = Image.open(io.BytesIO(data)).resize((260, 180))
            tk_img = ImageTk.PhotoImage(im)
            lbl = tk.Label(img_frame, image=tk_img, bg="white")
            lbl.image = tk_img
            lbl.pack()
        except:
            tk.Label(img_frame, text="Không có ảnh", fg="red").pack()


        tk.Button(
            self,
            text="🔍 Xem chi tiết giao dịch",
            font=("Arial", 13),
            bg=BLUE, fg="white",
            command=lambda: AdminUI(self, cloud_api)
        ).pack(pady=15)


# ==========================================================
# MAIN GATE UI
# ==========================================================
class GateMain(tk.Tk):
    def __init__(self, username, gateid, role="guard"):
        super().__init__()

        self.username = username
        self.gateid = gateid
        self.role = role.lower()

        cfg = load_config()
        self.cloud = cfg["CLOUD_API"]

        self.title(f"Gate {gateid} – Parking System ({role})")
        self.geometry("1250x780")
        self.configure(bg=BG)

        # SQLite
        self.local_conn = sqlite3.connect(DB_PATH)
        self.local_cur = self.local_conn.cursor()
        self.slots = []
        self.slot_boxes = []

        # UI
        self._build_header()
        self._build_toolbar()

        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.tooltip = Tooltip(self.canvas)
        self.canvas.bind("<Motion>", self.on_hover)
        self.canvas.bind("<Button-1>", self.on_click_slot)

        self._build_dashboard()

        # Load & start
        self.refresh()
        self.after(100, self.process_ws_events)
        self.after(POLL * 1000, self.auto_update)


    # ==========================================================
    def _build_header(self):
        header = tk.Frame(self, bg=GREEN, height=55)
        header.pack(fill="x")

        tk.Label(header,
                 text=f"🚗 Parking Gate – {self.gateid}",
                 font=("Segoe UI", 20, "bold"),
                 bg=GREEN, fg="white").pack(side="left", padx=20)

        if self.role == "admin":
            tk.Label(header, text="ADMIN",
                     bg="#f1c40f", fg="black",
                     padx=12, pady=2,
                     font=("Segoe UI", 12, "bold")).pack(side="left")

        self.status = tk.Label(header,
                               text="⏳ Đang tải...",
                               bg=GREEN, fg="white",
                               font=("Segoe UI", 12))
        self.status.pack(side="right", padx=20)

    # ==========================================================
    def _build_toolbar(self):
        bar = tk.Frame(self, bg="#dfe6e9", height=45)
        bar.pack(fill="x")

        def btn(text, cmd, color=GREEN):
            b = tk.Button(bar, text=text, command=cmd,
                          bg=color, fg="white",
                          relief="flat",
                          font=("Segoe UI", 11, "bold"))
            b.pack(side="left", padx=8)
            return b

        btn("🔄 Refresh", self.refresh)
        btn("🚗 Xe vào", self.vehicle_in)
        btn("🚙 Xe ra", self.vehicle_out, "#16a085")
        btn("☁ Full Sync", self.full_sync, GRAY)
        btn("🛡 Giao diện bảo vệ",
            lambda: SecurityUI(self, self.cloud, self.gateid),
            BLUE)

        if self.role == "admin":
            btn("📊 Admin", lambda: AdminUI(self, self.cloud), BLUE)
            btn("⚙️ Cài đặt", self.open_settings, GRAY)


    # ==========================================================
    def _build_dashboard(self):
        self.dashboard = tk.Frame(self, bg=BG)
        self.dashboard.place(x=1020, y=70)

        self.total_label = tk.Label(self.dashboard, text="Slots: ?",
                                    bg=BG, font=("Segoe UI", 12))
        self.total_label.pack(anchor="e", pady=3)

        self.free_label = tk.Label(self.dashboard, text="Trống: ?",
                                   bg=BG, font=("Segoe UI", 12))
        self.free_label.pack(anchor="e", pady=3)

        self.cloud_label = tk.Label(self.dashboard, text="Cloud: ?",
                                    bg=BG, font=("Segoe UI", 12))
        self.cloud_label.pack(anchor="e", pady=3)


    # ==========================================================
    # LOAD CLOUD → LOCAL CACHE
    # ==========================================================
    def load_cloud(self):
        try:
            r = requests.get(f"{self.cloud}/slots",
                             headers={"Authorization": "Bearer secret-key"},
                             params={"gate_id": self.gate_id},
                             timeout=4)
            self.slots = r.json()["slots"]
            self.save_local()

            self.status.config(text="🟢 Cloud Online")
            self.cloud_label.config(text="Cloud: Online", fg=GREEN)
        except:
            self.load_local()
            self.status.config(text="🔴 Cloud Offline — Local Mode")
            self.cloud_label.config(text="Cloud: Offline", fg=RED)
    

    def save_local(self):
        self.local_cur.execute("DELETE FROM local_slots")
        for s in self.slots:
            self.local_cur.execute("""
                INSERT INTO local_slots(slotid, zone, x, y, occupied, plate, version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (s["slotid"], s["zone"], s["x"], s["y"],
                  int(s["occupied"]), s["plate"], s["version"]))
        self.local_conn.commit()


    def load_local(self):
        rows = self.local_cur.execute(
            "SELECT slotid, zone, x, y, occupied, plate, version FROM local_slots"
        ).fetchall()
        self.slots = [{
            "slotid": r[0], "zone": r[1], "x": r[2], "y": r[3],
            "occupied": bool(r[4]), "plate": r[5], "version": r[6]
        } for r in rows]


    # ==========================================================
    # VẼ BẢN ĐỒ SLOT
    # ==========================================================
    def draw_map(self):
        self.canvas.delete("all")
        self.slot_boxes = []

        SCALE = 42
        GRID_W = 10
        GRID_H = 6

        W = self.canvas.winfo_width()
        H = self.canvas.winfo_height()

        cx = W // 2
        cy = H // 2 + 40

        start_x = cx - (GRID_W * SCALE) // 2
        start_y = cy - (GRID_H * SCALE) // 2

        for s in self.slots:
            x = start_x + s["x"] * SCALE
            y = start_y + s["y"] * SCALE

            color = RED if s["occupied"] else GREEN_LIGHT

            rect = self.canvas.create_rectangle(
                x, y, x + SCALE - 4, y + SCALE - 4,
                fill=color, outline="white", width=2
            )
            self.canvas.create_text(
                x + SCALE//2, y + SCALE//2,
                text=s["slotid"], fill="white",
                font=("Segoe UI", 10, "bold")
            )

            self.slot_boxes.append({
                "id": rect,
                "slotid": s["slotid"],
                "plate": s["plate"],
                "x": x,
                "y": y
            })

        self.total_label.config(text=f"Slots: {len(self.slots)}")
        self.free_label.config(text=f"Trống: {sum(not s['occupied'] for s in self.slots)}")


    # ==========================================================
    # HOVER SLOT (CÓ ẢNH)
    # ==========================================================
    def on_hover(self, event):
        hovered = None
        for b in self.slot_boxes:
            if b["x"] <= event.x <= b["x"] + 42 and b["y"] <= event.y <= b["y"] + 42:
                hovered = b
                break

        if not hovered:
            self.tooltip.hide()
            return

        slot = hovered["slotid"]

        # Lấy dữ liệu chi tiết từ Cloud
        try:
            r = requests.get(f"{self.cloud}/slot_info/{slot}",
                             headers={"Authorization": "Bearer secret-key"})
            info = r.json().get("info")
        except:
            info = None

        if not info:
            self.tooltip.show_text(event.x, event.y,
                                   f"Slot {slot}\nTrống")
            return

        plate = info["plate"]
        time_in = info["time_in"]

        # Load ảnh nhỏ
        thumbnail = None
        if info.get("img_in"):
            try:
                url = f"{self.cloud}/view_image?path={info['img_in']}"
                im = Image.open(io.BytesIO(requests.get(url).content))
                thumbnail = im
            except:
                thumbnail = None

        text = f"Slot {slot}\nBiển số: {plate}\nVào: {time_in}"

        if thumbnail:
            self.tooltip.show_with_image(event.x, event.y, text, thumbnail)
        else:
            self.tooltip.show_text(event.x, event.y, text)


    # ==========================================================
    # CLICK SLOT → MỞ CHI TIẾT
    # ==========================================================
    def on_click_slot(self, event):
        for b in self.slot_boxes:
            if b["x"] <= event.x <= b["x"] + 42 and b["y"] <= event.y <= b["y"] + 42:
                slot = b["slotid"]
                self.open_slot_detail(slot)
                return

    def open_slot_detail(self, slot):
        try:
            r = requests.get(f"{self.cloud}/slot_info/{slot}",
                             headers={"Authorization": "Bearer secret-key"})
            data = r.json().get("info")
            if not data:
                messagebox.showinfo("Slot trống", f"Slot {slot} đang trống.")
                return

            data["slotid"] = slot
            SlotDetailWindow(self, data, self.cloud)
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))


    # ==========================================================
    # WS EVENT
    # ==========================================================
    def process_ws_events(self):
        try:
            while not GUI_EVENT_QUEUE.empty():
                evt = GUI_EVENT_QUEUE.get_nowait()

                if evt.get("type") == "slot_update":
                    self.apply_slot_update(evt)
                elif evt.get("type") == "heartbeat":
                    self.cloud_label.config(text="Cloud: Online", fg=GREEN)
        except:
            pass

        self.after(100, self.process_ws_events)


    def apply_slot_update(self, evt):
        slotid = evt.get("slotId")
        occupied = evt.get("occupied")
        plate = evt.get("plate")

        if slotid:
            for s in self.slots:
                if s["slotid"] == slotid:
                    s["occupied"] = occupied
                    s["plate"] = plate
        self.draw_map()


    # ==========================================================
    # Button handlers
    # ==========================================================
    def refresh(self):
        self.load_cloud()
        self.draw_map()

    def auto_update(self):
        self.refresh()
        self.after(POLL * 1000, self.auto_update)

    def vehicle_in(self):
        messagebox.showinfo("Xe vào", "Demo")

    def vehicle_out(self):
        messagebox.showinfo("Xe ra", "Demo")

    def full_sync(self):
        messagebox.showinfo("Sync", "Đã full sync")

    def open_settings(self):
        new_api = simpledialog.askstring(
            "Cloud API",
            "Nhập Cloud API",
            initialvalue=self.cloud
        )

        if new_api:
            save_config({"CLOUD_API": new_api})
            messagebox.showinfo("OK", "Vui lòng mở lại ứng dụng.")

