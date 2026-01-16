from fastapi import FastAPI, Body, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import os, requests, sqlite3, asyncio
from datetime import datetime
from gate_ws import send_event

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "gate_local.db")

GATE_ID = os.getenv("GATE_ID", "G_N")
CLOUD_API = os.getenv("CLOUD_API", "http://localhost:8010")
SECRET = "secret-key"

app = FastAPI(title=f"Gate Node {GATE_ID}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ==========================================================
# LOCAL DB (OFFLINE QUEUE)
# ==========================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS local_event_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            payload TEXT,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_local_event(event_type: str, payload: dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO local_event_queue (event_type, payload, status)
        VALUES (?, ?, 'pending')
    """, (event_type, str(payload)))
    conn.commit()
    conn.close()


# ==========================================================
# IMAGE UPLOAD
# ==========================================================
@app.post("/upload_image_in")
async def upload_image_in(
    file: UploadFile = File(...),
    plate: str = Form(...),
    gate: str = Form(...)
):
    files = {"file": (file.filename, await file.read(), file.content_type)}
    data = {"plate": plate, "gate": gate}

    r = requests.post(
        f"{CLOUD_API}/upload_image_in",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {SECRET}"},
        timeout=10
    )
    return r.json()


@app.post("/upload_image_out")
async def upload_image_out(
    file: UploadFile = File(...),
    plate: str = Form(...),
    gate: str = Form(...)
):
    files = {"file": (file.filename, await file.read(), file.content_type)}
    data = {"plate": plate, "gate": gate}

    r = requests.post(
        f"{CLOUD_API}/upload_image_out",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {SECRET}"}
    )
    return r.json()


# ==========================================================
# VEHICLE IN
# ==========================================================
@app.post("/vehicle_in")
async def vehicle_in(req: dict = Body(...)):
    payload = {
        "plate": req.get("plate"),
        "slot": req.get("slot"),
        "gate": req.get("gate"),
        "img_in": req.get("img_in")
    }

    try:
        r = requests.post(
            f"{CLOUD_API}/vehicle_in",
            json=payload,
            headers={"Authorization": f"Bearer {SECRET}"},
            timeout=5
        )
        res = r.json()
    except:
        save_local_event("vehicle_in", payload)
        res = {"ok": False, "msg": "Cloud offline → lưu local queue"}

    await send_event({
        "type": "sync_event",
        "event": {"type": "vehicle_in", **payload}
    })

    return res


# ==========================================================
# VEHICLE OUT
# ==========================================================
@app.post("/vehicle_out")
async def vehicle_out(req: dict = Body(...)):
    payload = {
        "plate": req.get("plate"),
        "gate": req.get("gate"),
        "img_out": req.get("img_out")
    }

    try:
        r = requests.post(
            f"{CLOUD_API}/vehicle_out",
            json=payload,
            headers={"Authorization": f"Bearer {SECRET}"},
            timeout=5
        )
        res = r.json()
    except:
        save_local_event("vehicle_out", payload)
        res = {"ok": False, "msg": "Cloud offline → lưu local queue"}

    await send_event({
        "type": "sync_event",
        "event": {"type": "vehicle_out", **payload}
    })

    return res


# ==========================================================
# HEALTH CHECK
# ==========================================================
@app.get("/health")
def health():
    return {"ok": True, "gate": GATE_ID, "time": datetime.now().isoformat()}


# ==========================================================
# SYNC LOCAL EVENTS BACK TO CLOUD (OFFLINE QUEUE)
# ==========================================================
async def sync_local_events():
    await asyncio.sleep(3)
    while True:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id, event_type, payload FROM local_event_queue WHERE status='pending'"
        ).fetchall()

        for event_id, event_type, payload in rows:
            try:
                ok = await send_event({
                    "type": "sync_event",
                    "event": {"type": event_type, "payload": payload}
                })
                if ok:
                    cur.execute("UPDATE local_event_queue SET status='done' WHERE id=?", (event_id,))
                    conn.commit()
            except:
                pass

        conn.close()
        await asyncio.sleep(3)


# ==========================================================
# START SYNC THREAD
# ==========================================================
import threading

def start_sync_thread():
    loop = asyncio.new_event_loop()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(sync_local_events())

    t = threading.Thread(target=run, daemon=True)
    t.start()

start_sync_thread()
