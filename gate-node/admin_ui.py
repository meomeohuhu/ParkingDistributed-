import tkinter as tk
from tkinter import ttk, messagebox
import requests
import io
from PIL import Image, ImageTk
from datetime import datetime
import pytz

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

TZ = pytz.timezone("Asia/Ho_Chi_Minh")
HEADERS = {"Authorization": "Bearer secret-key"}


# =====================================================================
#  FORMAT THỜI GIAN
# =====================================================================
def parse_time(t):
    if not t:
        return None
    try:
        if "T" not in t:
            t = t.replace(" ", "T")
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = TZ.localize(dt)
        return dt
    except:
        return None



def fmt(dt):
    if not dt:
        return "None"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# =====================================================================
#  GIAO DIỆN CHI TIẾT GIAO DỊCH
# =====================================================================
class TransactionDetailUI:
    def __init__(self, parent, api, tx):
        self.api = api
        self.tx = tx

        time_in_vn = parse_time(tx["time_in"])
        time_out_vn = parse_time(tx["time_out"])

        self.win = tk.Toplevel(parent)
        self.win.title(f"Chi tiết giao dịch – {tx['plate']}")
        self.win.state("zoomed")
        self.win.configure(bg="white")

        header = tk.Frame(self.win, bg="white")
        header.pack(pady=10)

        tk.Label(header, text=f"Biển số: {tx['plate']}",
                 font=("Arial", 32, "bold"),
                 fg="#2c3e50", bg="white").pack()

        tk.Label(header, text=f"Slot: {tx['slotid']}   |   Gate: {tx['gateid']}",
                 font=("Arial", 20), bg="white").pack()

        fee = tx["fee"] or 0

        duration_str = "Chưa rời bãi"
        if tx["duration_minutes"]:
            mins = tx["duration_minutes"]
            duration_str = f"{mins//60} giờ {mins%60} phút"

        tk.Label(header, text=f"Vào: {fmt(time_in_vn)}    |    Ra: {fmt(time_out_vn)}",
                 font=("Arial", 18), bg="white").pack(pady=5)

        tk.Label(header, text=f"Thời gian đậu: {duration_str}",
                 font=("Arial", 18), bg="white").pack(pady=5)

        tk.Label(header, text=f"Tiền: {fee:,} VND",
                 font=("Arial", 26, "bold"), fg="blue", bg="white").pack(pady=10)

        img_frame = tk.Frame(self.win, bg="white")
        img_frame.pack(pady=20, fill="both", expand=True)

        left = tk.Frame(img_frame, bg="white")
        left.pack(side="left", expand=True)

        tk.Label(left, text="Ảnh xe vào",
                 font=("Arial", 20, "bold"), bg="white").pack(pady=10)
        self.show_image(left, tx["img_in"])

        right = tk.Frame(img_frame, bg="white")
        right.pack(side="right", expand=True)

        tk.Label(right, text="Ảnh xe ra",
                 font=("Arial", 20, "bold"), bg="white").pack(pady=10)
        self.show_image(right, tx["img_out"])

    def show_image(self, parent, path):
        if not path:
            tk.Label(parent, text="Không có ảnh",
                     fg="red", bg="white").pack()
            return

        try:
            url = f"{self.api}/view_image?path={path}"
            img = Image.open(io.BytesIO(
                requests.get(url, headers=HEADERS).content
            ))

            img = img.resize((450, 300))

            tk_img = ImageTk.PhotoImage(img)
            lbl = tk.Label(parent, image=tk_img, bg="white")
            lbl.image = tk_img
            lbl.pack(pady=10)

        except:
            tk.Label(parent, text="Lỗi tải ảnh",
                     fg="red", bg="white").pack()


# =====================================================================
#  ADMIN UI
# =====================================================================
class AdminUI:
    def __init__(self, parent, cloud_api):
        self.api = cloud_api

        self.win = tk.Toplevel(parent)
        self.win.title("Admin Dashboard")
        self.win.state("zoomed")
        self.win.configure(bg="#ecf0f1")

        tab = ttk.Notebook(self.win)
        tab.pack(fill="both", expand=True)

        self.tab_dash = ttk.Frame(tab)
        self.tab_history = ttk.Frame(tab)
        self.tab_slot = ttk.Frame(tab)
        self.tab_stats = ttk.Frame(tab)

        tab.add(self.tab_dash, text="📊 Dashboard")
        tab.add(self.tab_history, text="📜 Lịch sử")
        tab.add(self.tab_slot, text="🅿 Slot Manager")
        tab.add(self.tab_stats, text="📈 Thống kê – Báo cáo")
      


        self.build_dashboard()
        self.build_history()
        self.build_slotmanager()
        self.build_stats()

    # =================================================================
    # DASHBOARD
    # =================================================================
    def build_dashboard(self):
        f = self.tab_dash

        tk.Label(f, text="PARKING DASHBOARD",
                 font=("Arial", 26, "bold")).pack(pady=20)

        self.stats_frame = tk.Frame(f, bg="#ecf0f1")
        self.stats_frame.pack(pady=20)

        self.load_stats()

    def load_stats(self):
        try:
            r = requests.get(self.api +  "/slots/map", headers=HEADERS)
            slots = r.json()["slots"]

            total = len(slots)
            used = sum(1 for s in slots if s["occupied"])
            free = total - used

            for w in self.stats_frame.winfo_children():
                w.destroy()

            def box(name, val):
                f = tk.Frame(self.stats_frame, bg="white",
                             padx=30, pady=20, relief="ridge")
                f.pack(side="left", padx=20)
                tk.Label(f, text=name, font=("Arial", 16)).pack()
                tk.Label(f, text=str(val),
                         font=("Arial", 28, "bold"), fg="#2980b9").pack()

            box("Tổng Slot", total)
            box("Đang Trống", free)
            box("Xe Đang Đậu", used)

        except Exception as e:
            tk.Label(self.stats_frame, text=f"Lỗi: {e}", fg="red").pack()

    # =================================================================
    # LỊCH SỬ
    # =================================================================
    def build_history(self):
        f = self.tab_history

        tk.Label(f, text="LỊCH SỬ XE VÀO – RA",
                 font=("Arial", 22, "bold")).pack(pady=10)

        columns = ("time", "plate", "slot", "gate", "type")
        self.history_table = ttk.Treeview(
            f, columns=columns, show="headings")

        for col in columns:
            self.history_table.heading(col, text=col.upper())
            self.history_table.column(col, width=180)

        self.history_table.pack(fill="both", expand=True)

        tk.Button(f, text="🔄 Refresh",
                  command=self.load_history).pack(pady=10)

        self.history_table.bind("<Double-1>", self.open_detail)

        self.load_history()

    def load_history(self):
        try:
            r = requests.get(self.api + "/transactions", headers=HEADERS)
            txs = r.json()["transactions"]

            self.history_table.delete(*self.history_table.get_children())

            for t in txs:
                time_show = t["time_out"] or t["time_in"]
                typ = "OUT" if t["time_out"] else "IN"
                self.history_table.insert("", "end",
                                          values=(time_show, t["plate"], t["slotid"], t["gateid"], typ))
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    def open_detail(self, event):
        sel = self.history_table.focus()
        if not sel:
            return

        row = self.history_table.item(sel, "values")
        time_click, plate, slot, gate, _ = row

        r = requests.get(self.api + "/transactions", headers=HEADERS)
        txs = r.json()["transactions"]

        tx = next((
            x for x in txs
            if x["plate"] == plate and
            (x["time_in"] == time_click or x["time_out"] == time_click)
        ), None)


        if not tx:
            messagebox.showerror("Lỗi", "Không tìm thấy giao dịch")
            return

        TransactionDetailUI(self.win, self.api, tx)

    # =================================================================
    # QUẢN LÝ SLOT
    # =================================================================
    def build_slotmanager(self):
        f = self.tab_slot

        tk.Label(
            f,
            text="QUẢN LÝ SLOT (ADMIN)",
            font=("Arial", 22, "bold")
        ).pack(pady=30)

        tk.Button(
            f,
            text="🅿 Mở giao diện Thêm / Sửa / Xóa Slot",
            font=("Arial", 16),
            bg="#2980b9",
            fg="white",
            width=35,
            height=2,
            command=lambda: SlotManagerUI(self.win, self.api)
        ).pack(pady=40)


    # =================================================================
    #  THỐNG KÊ – BÁO CÁO
    # =================================================================
    def build_stats(self):
        f = self.tab_stats

        tk.Label(f, text="THỐNG KÊ – BÁO CÁO",
                 font=("Arial", 26, "bold")).pack(pady=10)

        filter_frame = tk.Frame(f, bg="#ecf0f1")
        filter_frame.pack(pady=5)

        tk.Label(filter_frame, text="Gate:", bg="#ecf0f1").grid(row=0, column=0)
        self.gate_filter = ttk.Combobox(filter_frame, values=["ALL"], width=10)
        self.gate_filter.grid(row=0, column=1, padx=5)
        self.gate_filter.current(0)

        tk.Label(filter_frame, text="Từ ngày:", bg="#ecf0f1").grid(row=0, column=2)
        self.start_date = tk.Entry(filter_frame, width=12)
        self.start_date.grid(row=0, column=3, padx=5)

        tk.Label(filter_frame, text="Đến ngày:", bg="#ecf0f1").grid(row=0, column=4)
        self.end_date = tk.Entry(filter_frame, width=12)
        self.end_date.grid(row=0, column=5, padx=5)

        tk.Button(filter_frame, text="🔄 Lọc",
                  command=self.load_revenue_stats).grid(row=0, column=6, padx=10)

        tk.Button(filter_frame, text="📄 Xuất PDF",
                  command=self.export_pdf).grid(row=0, column=7)

        self.stats_container = tk.Frame(f, bg="#ecf0f1")
        self.stats_container.pack(fill="both", expand=True)

        self.load_gate_list()
        self.load_revenue_stats()



    def load_gate_list(self):
        try:
            r = requests.get(self.api + "/gates", headers=HEADERS)
            gates = ["ALL"] + [g["gateid"] for g in r.json()["gates"]]
            self.gate_filter["values"] = gates
        except Exception as e:
            print("load_gate_list error:", e)


    # =================================================================
    # LOAD + SHOW REPORT
    # =================================================================
    def load_revenue_stats(self):
        for w in self.stats_container.winfo_children():
            w.destroy()

        try:
            r = requests.get(self.api + "/transactions", headers=HEADERS)
            txs = r.json()["transactions"]
            if not txs:
                tk.Label(
                    self.stats_container,
                    text="❗ Không có dữ liệu thống kê",
                    font=("Arial", 16),
                    fg="red",
                    bg="#ecf0f1"
                ).pack(pady=30)
                return

        except Exception as e:
            tk.Label(self.stats_container, text=f"Lỗi tải dữ liệu: {e}", fg="red").pack()
            return

        gate = self.gate_filter.get()
        sd = self.start_date.get().strip()
        ed = self.end_date.get().strip()

        def valid_time(tx):
            # ⚠️ CHỈ DÙNG time_in để thống kê
            t = parse_time(tx["time_in"])
            if not t:
                return False

            try:
                if sd and t.date() < datetime.fromisoformat(sd).date():
                    return False
                if ed and t.date() > datetime.fromisoformat(ed).date():
                    return False
            except:
                pass

            return True


        if gate != "ALL":
            txs = [t for t in txs if t["gateid"] == gate]

        txs = [t for t in txs if valid_time(t)]

        total = len(txs)
        total_out = sum(1 for t in txs if t["time_out"])
        revenue = sum((t["fee"] or 0) for t in txs)

        stats_frame = tk.Frame(self.stats_container, bg="#ecf0f1")
        stats_frame.pack(pady=10)

        def stat(title, value):
            f = tk.Frame(stats_frame, bg="white", padx=20, pady=10, relief="ridge")
            f.pack(side="left", padx=25)
            tk.Label(f, text=title, font=("Arial", 14)).pack()
            tk.Label(f, text=value, fg="#2980b9",
                     font=("Arial", 22, "bold")).pack()

        stat("Tổng giao dịch", total)
        stat("Xe rời bãi", total_out)
        stat("Doanh thu", f"{revenue:,} VND")

        self.draw_chart(self.stats_container, txs)

    # =================================================================
    # DRAW CHART
    # =================================================================
    def draw_chart(self, parent, txs):
        for w in parent.winfo_children():
            if isinstance(w, FigureCanvasTkAgg):
                w.get_tk_widget().destroy()

        day_count = {}
        for t in txs:
            dt = parse_time(t["time_in"])
            if not dt:
                continue
            d = dt.date()
            day_count[d] = day_count.get(d, 0) + 1

        if not day_count:
            tk.Label(
                parent,
                text="Không có dữ liệu để vẽ biểu đồ",
                font=("Arial", 14),
                fg="red",
                bg="#ecf0f1"
            ).pack(pady=20)
            return

        days = list(day_count.keys())
        counts = list(day_count.values())

        fig = Figure(figsize=(10, 4.5), dpi=100)
        ax = fig.add_subplot(111)

        ax.plot(days, counts, marker="o", linewidth=2.5)
        ax.set_title("Lượt xe theo ngày", fontsize=16)
        ax.grid(True, linestyle="--", alpha=0.4)

        chart = FigureCanvasTkAgg(fig, parent)
        chart.draw()
        chart.get_tk_widget().pack(pady=10, fill="both", expand=True)


    # =================================================================
    # EXPORT PDF
    # =================================================================
    def export_pdf(self):
        filename = "parking_report.pdf"

        try:
            c = canvas.Canvas(filename, pagesize=A4)
            w, h = A4

            gate = self.gate_filter.get()
            sd = self.start_date.get()
            ed = self.end_date.get()

            c.setFont("Helvetica-Bold", 20)
            c.drawString(40, h - 50, "BAO CAO THONG KE BAI DO XE")

            c.setFont("Helvetica", 12)
            c.drawString(40, h - 80, f"Gate: {gate}")
            c.drawString(200, h - 80, f"TU: {sd or '---'}")
            c.drawString(350, h - 80, f"DEN: {ed or '---'}")

            # Load tất cả giao dịch
            r = requests.get(self.api + "/transactions", headers=HEADERS)
            txs = r.json()["transactions"]

            # Lọc
            if gate != "ALL":
                txs = [t for t in txs if t["gateid"] == gate]

            if sd:
                txs = [t for t in txs
                       if parse_time(t["time_out"] or t["time_in"]).date() >= datetime.fromisoformat(sd).date()]

            if ed:
                txs = [t for t in txs
                       if parse_time(t["time_out"] or t["time_in"]).date() <= datetime.fromisoformat(ed).date()]

            revenue = sum((t["fee"] or 0) for t in txs)

            # Tổng quan báo cáo
            c.setFont("Helvetica-Bold", 14)
            c.drawString(40, h - 110,
                         f"➤ TONG: {len(txs)} giao dịch   |   Doanh thu: {revenue:,} VND")

            y = h - 140
            c.setFont("Helvetica", 11)

            for t in txs:
                line = f"{fmt(parse_time(t['time_in']))} | {t['plate']} | Slot {t['slotid']} | Fee: {t['fee'] or 0:,} VND"
                c.drawString(40, y, line)
                y -= 18

                if y < 40:
                    c.showPage()
                    y = h - 60

            c.save()
            messagebox.showinfo("OK", f"Đã xuất báo cáo: {filename}")

        except Exception as e:
            messagebox.showerror("Lỗi PDF", str(e))

class SlotManagerUI:
    def __init__(self, parent, api):
        self.api = api

        self.win = tk.Toplevel(parent)
        self.win.title("Quản lý Slot (Admin)")
        self.win.geometry("700x500")

        # ================= FORM =================
        form = tk.Frame(self.win)
        form.pack(pady=10)

        tk.Label(form, text="Slot ID").grid(row=0, column=0, padx=5, pady=5)
        self.slotid = tk.Entry(form, width=10)
        self.slotid.grid(row=0, column=1)

        tk.Label(form, text="Zone").grid(row=0, column=2, padx=5)
        self.zone = tk.Entry(form, width=5)
        self.zone.grid(row=0, column=3)

        tk.Label(form, text="X").grid(row=1, column=0)
        self.x = tk.Entry(form, width=10)
        self.x.grid(row=1, column=1)

        tk.Label(form, text="Y").grid(row=1, column=2)
        self.y = tk.Entry(form, width=10)
        self.y.grid(row=1, column=3)

        # ================= BUTTON =================
        btns = tk.Frame(self.win)
        btns.pack(pady=10)

        tk.Button(btns, text="➕ Thêm",
                  bg="#27ae60", fg="white",
                  width=12, command=self.add_slot).pack(side="left", padx=5)

        tk.Button(btns, text="✏️ Sửa",
                  bg="#2980b9", fg="white",
                  width=12, command=self.update_slot).pack(side="left", padx=5)

        tk.Button(btns, text="🗑 Xóa",
                  bg="#c0392b", fg="white",
                  width=12, command=self.delete_slot).pack(side="left", padx=5)

        # ================= TABLE =================
        columns = ("slotid", "zone", "x", "y", "status")
        self.table = ttk.Treeview(self.win, columns=columns, show="headings")

        for c in columns:
            self.table.heading(c, text=c.upper())
            self.table.column(c, width=100)

        self.table.pack(fill="both", expand=True, pady=10)
        self.table.bind("<<TreeviewSelect>>", self.on_select)

        self.load_slots()
    

    def load_slots(self):
        try:
            r = requests.get(self.api + "/slots/map", headers=HEADERS)
            slots = r.json()["slots"]

            self.table.delete(*self.table.get_children())

            for s in slots:
                status = "Đang đậu" if s["occupied"] else "Trống"
                self.table.insert("", "end",
                                  values=(s["slotid"], s["zone"],
                                          s["x"], s["y"], status))
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    def on_select(self, event):
        sel = self.table.focus()
        if not sel:
            return

        slotid, zone, x, y, _ = self.table.item(sel, "values")

        self.slotid.delete(0, "end")
        self.slotid.insert(0, slotid)
        self.slotid.config(state="disabled")

        self.zone.delete(0, "end")
        self.zone.insert(0, zone)

        self.x.delete(0, "end")
        self.x.insert(0, x)

        self.y.delete(0, "end")
        self.y.insert(0, y)

    def add_slot(self):
        try:
            data = {
                "slotid": self.slotid.get().strip(),
                "zone": self.zone.get().strip(),
                "x": int(self.x.get()),
                "y": int(self.y.get())
            }

            r = requests.post(self.api + "/admin/slots",
                              json=data,
                              headers=HEADERS)

            if r.status_code != 200:
                raise Exception(r.text)

            messagebox.showinfo("OK", "Đã thêm slot")
            self.load_slots()
            self.slotid.config(state="normal")


        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    def update_slot(self):
        try:
            slotid = self.slotid.get()
            data = {
                "zone": self.zone.get(),
                "x": int(self.x.get()),
                "y": int(self.y.get())
            }

            r = requests.put(
                f"{self.api}/admin/slots/{slotid}",
                json=data,
                headers=HEADERS
            )

            if r.status_code != 200:
                raise Exception(r.text)

            messagebox.showinfo("OK", "Đã cập nhật slot")
            self.load_slots()
            

        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    def delete_slot(self):
        slotid = self.slotid.get()
        if not slotid:
            return

        if not messagebox.askyesno("Xác nhận", f"Xóa slot {slotid}?"):
            return

        try:
            r = requests.delete(
                f"{self.api}/admin/slots/{slotid}",
                headers=HEADERS
            )

            if r.status_code != 200:
                raise Exception(r.text)

            messagebox.showinfo("OK", "Đã xóa slot")
            self.slotid.config(state="normal")
            self.slotid.delete(0, "end")
            self.load_slots()
            self.slotid.config(state="normal")


        except Exception as e:
            messagebox.showerror("Lỗi", str(e))
