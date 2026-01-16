import tkinter as tk
from tkinter import messagebox
import requests, threading
from config import save_config, load_config
import gate_app

from gate_ws import start_ws  # WebSocket client

LOCAL_API = "http://localhost:8000"

# ======================================================
# CLOUD LOGIN HELPER
# ======================================================
def login_to_cloud(ip, user, pw):
    try:
        url = f"http://{ip}:8010/login"
        r = requests.post(
            url,
            json={"username": user, "password": pw},
            timeout=5
        )
        j = r.json()
        if j.get("ok"):
            return j
        raise Exception(j.get("detail", "Login failed"))
    except Exception as e:
        raise Exception(f"Login error: {e}")




# ======================================================
# CLOUD CONFIG WINDOW (USER INPUTS IP CLOUD)
# ======================================================
class CloudConfig(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cloud API Setup")
        self.geometry("300x150")

        tk.Label(self, text="Nhập IP Cloud:").pack(pady=8)
        self.entry = tk.Entry(self)
        self.entry.pack()

        tk.Button(self, text="Tiếp tục", command=self.save_ip).pack(pady=10)
        self.msg = tk.Label(self, text="")
        self.msg.pack()

    def save_ip(self):
        ip = self.entry.get().strip()
        if not ip:
            self.msg.config(text="IP không hợp lệ")
            return

        cfg = load_config()
        cfg["CLOUD_API"] = f"http://{ip}:8010"
        save_config(cfg)

        self.destroy()
        LoginWindow().mainloop()


# ======================================================
# LOGIN WINDOW
# ======================================================
class LoginWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        cfg = load_config()

        # Lấy IP Cloud đã nhập
        self.ip = cfg["CLOUD_API"].replace("http://", "").split(":")[0]

        self.title("Đăng nhập Gate")
        self.geometry("280x220")

        tk.Label(self, text=f"Cloud: {cfg['CLOUD_API']}").pack(pady=(5, 0))

        tk.Label(self, text="Username").pack()
        self.user = tk.Entry(self)
        self.user.pack()

        tk.Label(self, text="Password").pack()
        self.pw = tk.Entry(self, show="*")
        self.pw.pack()

        self.msg = tk.Label(self, text="", fg="red")
        self.msg.pack()

        self.login_btn = tk.Button(self, text="Đăng nhập", command=self.do_login)
        self.login_btn.pack(pady=10)

    # ==================================================
    # LOGIN HANDLER
    # ==================================================
    def do_login(self):
        user = self.user.get().strip()
        pw = self.pw.get().strip()

        if not user or not pw:
            messagebox.showerror("Lỗi", "Vui lòng nhập đầy đủ!")
            return

        self.login_btn.config(state="disabled")

        def worker():
            try:
                # 1) GỌI CLOUD LOGIN API
                res = login_to_cloud(self.ip, user, pw)

                gateid = res["gateid"]
                role   = res.get("role", "guard")

                # 2) LƯU CONFIG GATE NODE
                cfg = {
                    "CLOUD_API": f"http://{self.ip}:8010",
                    "GATE_ID": gateid,
                    "ROLE": role
                }
                save_config(cfg)

                # 3) CHẠY LOCAL API GATE NODE
                threading.Thread(
                    target=run_local_api,
                    args=(gateid, cfg["CLOUD_API"]),
                    daemon=True
                ).start()

                # 4) BẮT ĐẦU KẾT NỐI WEBSOCKET
                start_ws(self.ip, gateid)

                # 5) MỞ GIAO DIỆN CHÍNH
                self.after(0, self.open_main_gui, user, gateid, role)

            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Lỗi đăng nhập", str(e)))
                self.after(0, lambda: self.login_btn.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    # ==================================================
    # OPEN MAIN GUI
    # ==================================================
    def open_main_gui(self, user, gateid, role):
        if not self.winfo_exists():
            return
        self.destroy()

        from gui_main import GateMain
        GateMain(user, gateid, role).mainloop()


# ======================================================
# RUN LOCAL GATE FASTAPI
# ======================================================
def run_local_api(gateid, cloud_api):
    gate_app.GATE_ID = gateid
    gate_app.CLOUD_API = cloud_api

    import uvicorn
    uvicorn.run(gate_app.app, host="0.0.0.0", port=8000, reload=False)


# ======================================================
# MAIN ENTRY
# ======================================================
if __name__ == "__main__":
    cfg = load_config()
    if not cfg.get("CLOUD_API"):
        CloudConfig().mainloop()
    else:
        LoginWindow().mainloop()
