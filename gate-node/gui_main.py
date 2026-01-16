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
POLL = 5


# ==========================================================
# Tooltip nâng cấp (có thể chứa text + thumbnail)
# ==========================================================
class Tooltip:
    def __init__(self, canvas):
        self.canvas = canvas
        self.tip_text = None
        self.tip_image = None
        self.thumb = None   # ✅ giữ reference ảnh

    def hide(self):
        if self.tip_text:
            self.canvas.delete(self.tip_text)
            self.tip_text = None
        if self.tip_image:
            self.canvas.delete(self.tip_image)
            self.tip_image = None
            self.thumb = None

    def show_text(self, x, y, text):
        self.hide()
        self.tip_text = self.canvas.create_text(
            x, y - 14,
            text=text,
            fill="black",
            font=("Segoe UI", 11, "bold"),
            anchor="s"
        )

    def show_with_image(self, x, y, text, pil_image):
        self.hide()
        self.tip_text = self.canvas.create_text(
            x, y - 14,
            text=text,
            fill="black",
            font=("Segoe UI", 11, "bold"),
            anchor="s"
        )
        img = pil_image.resize((120, 90))
        self.thumb = ImageTk.PhotoImage(img)
        self.tip_image = self.canvas.create_image(
            x + 10, y - 110,
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

        tk.Label(self, text=f"Biển số: {info['plate']}",
                 bg="white", font=("Arial", 16)).pack(pady=5)

        tk.Label(self, text=f"Giờ vào: {info['time_in']}",
                 bg="white", font=("Arial", 14)).pack()

        img_frame = tk.Frame(self, bg="white")
        img_frame.pack(pady=20)

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

        self.cloud = load_config()["CLOUD_API"]

        self.title(f"Gate {gateid} – Parking System ({role})")
        self.geometry("1250x780")
        self.configure(bg=BG)

        self.local_conn = sqlite3.connect(DB_PATH)
        self.local_cur = self.local_conn.cursor()

        self.slots = []
        self.slot_boxes = []

        # ✅ cache hover
        self.slot_info_cache = {}
        self.last_hover_slot = None

        self._build_header()
        self._build_toolbar()

        self.canvas = tk.Canvas(self, bg="white", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.tooltip = Tooltip(self.canvas)
        self.canvas.bind("<Motion>", self.on_hover)
        self.canvas.bind("<Button-1>", self.on_click_slot)

        self._build_dashboard()

        self.refresh()
        self.after(100, self.process_ws_events)
        self.after(POLL * 1000, self.auto_update)

    # ==========================================================
    def _build_header(self):
        header = tk.Frame(self, bg=GREEN, height=55)
        header.pack(fill="x")

        tk.Label(
            header,
            text=f"🚗 Parking Gate – {self.gateid}",
            font=("Segoe UI", 20, "bold"),
            bg=GREEN, fg="white"
        ).pack(side="left", padx=20)

        if self.role == "admin":
            tk.Label(header, text="ADMIN",
                     bg="#f1c40f", fg="black",
                     padx=12, pady=2,
                     font=("Segoe UI", 12, "bold")).pack(side="left")

        self.status = tk.Label(
            header, text="⏳ Đang tải...",
            bg=GREEN, fg="white",
            font=("Segoe UI", 12)
        )
        self.status.pack(side="right", padx=20)

    # ==========================================================
    def _build_toolbar(self):
        bar = tk.Frame(self, bg="#dfe6e9", height=45)
        bar.pack(fill="x")

        def btn(text, cmd, color=GREEN):
            tk.Button(bar, text=text, command=cmd,
                      bg=color, fg="white",
                      relief="flat",
                      font=("Segoe UI", 11, "bold")
                      ).pack(side="left", padx=8)

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

        self.total_label = tk.Label(self.dashboard, text="Slots: 0",
                                    bg=BG, font=("Segoe UI", 12))
        self.total_label.pack(anchor="e", pady=3)

        self.free_label = tk.Label(self.dashboard, text="Trống: 0",
                                   bg=BG, font=("Segoe UI", 12))
        self.free_label.pack(anchor="e", pady=3)

        self.cloud_label = tk.Label(self.dashboard, text="Cloud: ?",
                                    bg=BG, font=("Segoe UI", 12))
        self.cloud_label.pack(anchor="e", pady=3)

        self.rtt_label = tk.Label(self.dashboard, text="RTT: -- ms",
                                  bg=BG, font=("Segoe UI", 12))
        self.rtt_label.pack(anchor="e", pady=3)

    # ==========================================================
    # LOAD CLOUD → LOCAL CACHE
    # ==========================================================
    def load_cloud(self):
        try:
            r = requests.get(
                f"{self.cloud}/slots/map",
                headers={"Authorization": "Bearer secret-key"},
                timeout=4
            )
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
    # VẼ BẢN ĐỒ SLOT (FIX FLOAT -> INT)
    # ==========================================================
    def draw_map(self):
        self.canvas.delete("all")
        self.slot_boxes.clear()

        if not self.slots:
            return

        W, H = self.canvas.winfo_width(), self.canvas.winfo_height()
        if W < 50:
            self.after(50, self.draw_map)
            return

        # ✅ ép int để cols/rows không thành float
        max_x = int(max(float(s["x"]) for s in self.slots))
        max_y = int(max(float(s["y"]) for s in self.slots))

        cols, rows = max_x + 1, max_y + 1
        MARGIN, PADDING = 40, 10

        # ✅ tính cell bằng / (ra float) rồi ép int cuối cùng
        cell = int(min(
            (W - MARGIN * 2) / cols,
            (H - MARGIN * 2) / rows
        ) - 8)

        SLOT_SIZE = int(max(22, cell))
        font_size = int(max(10, SLOT_SIZE // 5))

        # ✅ start_x/start_y cũng ép int để tọa độ ổn định
        start_x = int((W - (cols * SLOT_SIZE + (cols - 1) * PADDING)) / 2)
        start_y = int((H - (rows * SLOT_SIZE + (rows - 1) * PADDING)) / 2)

        for s in self.slots:
            sx = int(float(s["x"]))
            sy = int(float(s["y"]))

            x = int(start_x + sx * (SLOT_SIZE + PADDING))
            y = int(start_y + sy * (SLOT_SIZE + PADDING))

            occupied = bool(s["occupied"])
            color = RED if occupied else GREEN_LIGHT

            self.canvas.create_rectangle(
                x, y, x + SLOT_SIZE, y + SLOT_SIZE,
                fill=color, outline="white", width=2
            )
            self.canvas.create_text(
                x + SLOT_SIZE // 2, y + SLOT_SIZE // 2,
                text=s["slotid"], fill="white",
                font=("Segoe UI", font_size, "bold")
            )

            self.slot_boxes.append({
                "slotid": s["slotid"],
                "x": x, "y": y,
                "size": SLOT_SIZE
            })

    # ==========================================================
    # HOVER SLOT
    # ==========================================================
    def on_hover(self, event):
        hovered = None
        for b in self.slot_boxes:
            if b["x"] <= event.x <= b["x"] + b["size"] and \
               b["y"] <= event.y <= b["y"] + b["size"]:
                hovered = b
                break

        if not hovered:
            self.tooltip.hide()
            self.last_hover_slot = None
            return

        slot = hovered["slotid"]

        if slot != self.last_hover_slot:
            self.last_hover_slot = slot
            try:
                r = requests.get(
                    f"{self.cloud}/slot_info/{slot}",
                    headers={"Authorization": "Bearer secret-key"},
                    timeout=2
                )
                self.slot_info_cache[slot] = r.json().get("info")
            except:
                self.slot_info_cache[slot] = None

        info = self.slot_info_cache.get(slot)
        if not info:
            self.tooltip.show_text(event.x, event.y, f"Slot {slot}\nTrống")
            return

        text = f"Slot {slot}\nBiển số: {info['plate']}\nVào: {info['time_in']}"

        if info.get("img_in"):
            try:
                img = Image.open(io.BytesIO(
                    requests.get(f"{self.cloud}/view_image?path={info['img_in']}").content
                ))
                self.tooltip.show_with_image(event.x, event.y, text, img)
            except:
                self.tooltip.show_text(event.x, event.y, text)
        else:
            self.tooltip.show_text(event.x, event.y, text)

    # ==========================================================
    # CLICK SLOT
    # ==========================================================
    def on_click_slot(self, event):
        for b in self.slot_boxes:
            if b["x"] <= event.x <= b["x"] + b["size"] and \
               b["y"] <= event.y <= b["y"] + b["size"]:
                self.open_slot_detail(b["slotid"])
                return

    def open_slot_detail(self, slot):
        try:
            r = requests.get(
                f"{self.cloud}/slot_info/{slot}",
                headers={"Authorization": "Bearer secret-key"},
            )
            info = r.json().get("info")
            if info:
                info["slotid"] = slot
                SlotDetailWindow(self, info, self.cloud)
            else:
                messagebox.showinfo("Slot trống", f"Slot {slot} đang trống.")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    # ==========================================================
    # WS EVENT
    # ==========================================================
    def process_ws_events(self):
        while not GUI_EVENT_QUEUE.empty():
            evt = GUI_EVENT_QUEUE.get()
            if evt.get("type") == "slot_update":
                self.refresh()
            elif evt.get("type") == "heartbeat":
                self.cloud_label.config(text="Cloud: Online", fg=GREEN)
            elif evt.get("type") == "rtt":
                ms = evt.get("rtt_ms")
                if ms is not None:
                    self.rtt_label.config(text=f"RTT: {int(ms)} ms")
        self.after(100, self.process_ws_events)

    # ==========================================================
    # BUTTON HANDLERS
    # ==========================================================
    def refresh(self):
        self.load_cloud()
        self.total_label.config(text=f"Slots: {len(self.slots)}")
        self.free_label.config(
            text=f"Trống: {sum(1 for s in self.slots if not s['occupied'])}"
        )
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
            "Cloud API", "Nhập Cloud API", initialvalue=self.cloud
        )
        if new_api:
            save_config({"CLOUD_API": new_api})
            messagebox.showinfo("OK", "Vui lòng mở lại ứng dụng.")
