# gate_app.py
# ==========================================================
# Gate Node API (Distributed Mode)
# - Gate có LOCAL STATE (slots_local) để xe ra/vào khi Cloud OFF
# - Đồng bộ EVENT lên Cloud khi Cloud ON (offline queue)
# - Snapshot trạng thái slot từ Cloud về Gate định kỳ (last known state)
# - Upload ảnh: Cloud OFF thì lưu local; Cloud ON thì đẩy lên Cloud
# ==========================================================

import os
import json
import time
import uuid
import sqlite3
import asyncio
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List

import requests
from fastapi import FastAPI, Body, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# ============== Optional WS client ==============
# Bạn có file gate_ws.py, nếu import fail thì vẫn chạy bình thường.
try:
    from gate_ws import send_event  # async def send_event(message: dict) -> bool
except Exception:
    async def send_event(message: dict) -> bool:
        return False


# ==========================================================
# CONFIG
# ==========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "gate_local.db")

GATE_ID = os.getenv("GATE_ID", "G_N")
SECRET = os.getenv("SECRET_TOKEN", "secret-key")

# ưu tiên: ENV -> config.json -> default
DEFAULT_CLOUD = "http://cloud_api:8010"
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

CLOUD_API = os.getenv("CLOUD_API")
if not CLOUD_API:
    try:
        if os.path.exists(CONFIG_PATH):
            cfg = json.load(open(CONFIG_PATH, "r", encoding="utf-8"))
            CLOUD_API = (cfg.get("cloud_api") or cfg.get("CLOUD_API") or "").strip()
    except Exception:
        pass

CLOUD_API = CLOUD_API or DEFAULT_CLOUD

# local image storage
LOCAL_IMG_DIR = os.path.join(BASE_DIR, "local_images")
LOCAL_IN_DIR = os.path.join(LOCAL_IMG_DIR, "in")
LOCAL_OUT_DIR = os.path.join(LOCAL_IMG_DIR, "out")
os.makedirs(LOCAL_IN_DIR, exist_ok=True)
os.makedirs(LOCAL_OUT_DIR, exist_ok=True)

# ==========================================================
# FASTAPI
# ==========================================================
app = FastAPI(title=f"Gate Node {GATE_ID} (Local State + Offline Queue)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ==========================================================
# SQLITE HELPERS
# ==========================================================
def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _db()
    cur = conn.cursor()

    # 1) Local slot state (snapshot từ cloud + update realtime tại gate)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS slots_local (
            slotid TEXT PRIMARY KEY,
            zone   TEXT,
            x      REAL,
            y      REAL,
            occupied INTEGER NOT NULL DEFAULT 0,
            plate  TEXT,
            version INTEGER NOT NULL DEFAULT 0,
            last_cloud_sync_at TEXT
        )
    """)

    # 2) Sync state: lưu thời điểm cloud OK lần cuối (để chứng minh "last known state")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            k TEXT PRIMARY KEY,
            v TEXT
        )
    """)

    # 3) Offline queue (event + payload + status)
    # payload là JSON string
    cur.execute("""
        CREATE TABLE IF NOT EXISTS local_event_queue (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    
    conn.commit()
    conn.close()


init_db()


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def set_state(key: str, value: str) -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute("INSERT INTO sync_state(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))
    conn.commit()
    conn.close()

from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"ok": False, "msg": f"Gate API error: {type(exc).__name__}: {exc}"}
    )


def get_state(key: str) -> Optional[str]:
    conn = _db()
    cur = conn.cursor()
    row = cur.execute("SELECT v FROM sync_state WHERE k=?", (key,)).fetchone()
    conn.close()
    return row["v"] if row else None


def upsert_slots_from_cloud(slots: List[Dict[str, Any]]) -> None:
    """Upsert snapshot slots từ Cloud vào slots_local."""
    conn = _db()
    cur = conn.cursor()
    ts = now_iso()

    for s in slots:
        cur.execute(
            """
            INSERT INTO slots_local(slotid, zone, x, y, occupied, plate, version, last_cloud_sync_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(slotid) DO UPDATE SET
                zone=excluded.zone,
                x=excluded.x,
                y=excluded.y,
                occupied=excluded.occupied,
                plate=excluded.plate,
                version=excluded.version,
                last_cloud_sync_at=excluded.last_cloud_sync_at
            """,
            (
                s.get("slotid"),
                s.get("zone"),
                s.get("x"),
                s.get("y"),
                1 if s.get("occupied") else 0,
                s.get("plate"),
                int(s.get("version") or 0),
                ts
            )
        )

    conn.commit()
    conn.close()
    set_state("last_cloud_ok_at", ts)


def list_slots_local() -> List[Dict[str, Any]]:
    conn = _db()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT slotid, zone, x, y, occupied, plate, version, last_cloud_sync_at
        FROM slots_local
        ORDER BY slotid
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_slot_local(slotid: str) -> Optional[Dict[str, Any]]:
    conn = _db()
    cur = conn.cursor()
    row = cur.execute("""
        SELECT slotid, zone, x, y, occupied, plate, version, last_cloud_sync_at
        FROM slots_local
        WHERE slotid=?
    """, (slotid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_slot_local(slotid: str, occupied: bool, plate: Optional[str]) -> None:
    conn = _db()
    cur = conn.cursor()
    # tăng version local (không nhất thiết khớp cloud, nhưng giúp UI thấy thay đổi)
    cur.execute("""
        UPDATE slots_local
        SET occupied=?, plate=?, version=version+1
        WHERE slotid=?
    """, (1 if occupied else 0, plate, slotid))
    conn.commit()
    conn.close()


def enqueue_event(event_type: str, payload: Dict[str, Any]) -> str:
    event_id = payload.get("event_id") or str(uuid.uuid4())
    payload["event_id"] = event_id
    conn = _db()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO local_event_queue(event_id, event_type, payload, status, created_at)
        VALUES(?,?,?,?,?)
    """, (event_id, event_type, json.dumps(payload, ensure_ascii=False), "pending", now_iso()))
    conn.commit()
    conn.close()
    return event_id


def mark_event_done(event_id: str) -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute("UPDATE local_event_queue SET status='done' WHERE event_id=?", (event_id,))
    conn.commit()
    conn.close()


def get_pending_events(limit: int = 50) -> List[Dict[str, Any]]:
    conn = _db()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT event_id, event_type, payload, status, created_at
        FROM local_event_queue
        WHERE status='pending'
        ORDER BY created_at ASC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "event_id": r["event_id"],
            "event_type": r["event_type"],
            "payload": json.loads(r["payload"]),
            "created_at": r["created_at"]
        })
    return out


# ==========================================================
# CLOUD HELPERS
# ==========================================================
def cloud_health_ok(timeout: float = 1.5) -> bool:
    try:
        r = requests.get(f"{CLOUD_API}/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def cloud_upload_image(endpoint: str, local_path: str, plate: str, gate: str) -> Optional[str]:
    """Upload ảnh local lên Cloud, trả về cloud path nếu ok."""
    try:
        with open(local_path, "rb") as f:
            files = {"file": (os.path.basename(local_path), f.read(), "image/jpeg")}
        data = {"plate": plate, "gate": gate}
        r = requests.post(
            f"{CLOUD_API}{endpoint}",
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {SECRET}"},
            timeout=10
        )
        j = r.json()
        if j.get("ok") and j.get("path"):
            return j["path"]
    except Exception:
        pass
    return None


def cloud_post_json(endpoint: str, payload: Dict[str, Any], timeout: float = 5) -> Dict[str, Any]:
    r = requests.post(
        f"{CLOUD_API}{endpoint}",
        json=payload,
        headers={"Authorization": f"Bearer {SECRET}"},
        timeout=timeout
    )
    try:
        return r.json()
    except Exception:
        return {"ok": False, "msg": f"Bad cloud response ({r.status_code})"}


# ==========================================================
# API: LOCAL SLOTS (UI gọi LOCAL_API -> không phụ thuộc Cloud)
# ==========================================================
@app.get("/slots")
def api_slots(
    gate_id: str = Query(default=GATE_ID),
    mode: str = Query(default="in")  # in|out|all
):
    """
    Trả về slot list từ LOCAL DB (last known state + realtime update tại gate)
    mode=in: slot trống
    mode=out: slot đang có xe
    mode=all: tất cả
    """
    slots = list_slots_local()

    if mode.lower() == "in":
        slots = [s for s in slots if int(s.get("occupied") or 0) == 0]
    elif mode.lower() == "out":
        slots = [s for s in slots if int(s.get("occupied") or 0) == 1]

    return {
        "ok": True,
        "gate": gate_id,
        "mode": mode,
        "last_cloud_ok_at": get_state("last_cloud_ok_at"),
        "slots": slots
    }


@app.get("/slots/map")
def api_slots_map():
    """Dùng cho admin/UI map: trả tất cả slot từ local."""
    return {
        "ok": True,
        "last_cloud_ok_at": get_state("last_cloud_ok_at"),
        "slots": list_slots_local()
    }


@app.get("/suggest_slot/{gateid}")
def api_suggest_slot(gateid: str):
    """
    Suggest slot dựa trên LOCAL STATE.
    Nếu bạn có x,y gate/slot thì có thể tính distance.
    Hiện tại: chọn slot trống đầu tiên theo slotid.
    """
    slots = list_slots_local()
    free = [s for s in slots if int(s.get("occupied") or 0) == 0]
    free.sort(key=lambda x: x.get("slotid") or "")
    if not free:
        return {"ok": True, "slot": None, "distance": None, "gate": gateid, "source": "local"}
    return {"ok": True, "slot": free[0]["slotid"], "distance": None, "gate": gateid, "source": "local"}


# ==========================================================
# API: IMAGE UPLOAD (UI -> LOCAL_API, Cloud OFF vẫn lưu local)
# ==========================================================
def _save_local_image(kind: str, plate: str, content: bytes) -> str:
    ts = int(time.time())
    safe_plate = (plate or "UNKNOWN").replace("/", "_").replace("\\", "_")
    filename = f"{safe_plate}_{ts}.jpg"
    folder = LOCAL_IN_DIR if kind == "in" else LOCAL_OUT_DIR
    path = os.path.join(folder, filename)
    with open(path, "wb") as f:
        f.write(content)
    return path


@app.post("/upload_image_in")
async def upload_image_in(
    file: UploadFile = File(...),
    plate: str = Form(...),
    gate: str = Form(default=GATE_ID)
):
    content = await file.read()
    local_path = _save_local_image("in", plate, content)

    # best-effort push lên cloud ngay
    cloud_path = None
    if cloud_health_ok():
        cloud_path = cloud_upload_image("/upload_image_in", local_path, plate, gate)

    return {
        "ok": True,
        "local_path": local_path,
        "path": cloud_path or f"local:{local_path}"  # UI/gate event dùng cái này
    }


@app.post("/upload_image_out")
async def upload_image_out(
    file: UploadFile = File(...),
    plate: str = Form(...),
    gate: str = Form(default=GATE_ID)
):
    content = await file.read()
    local_path = _save_local_image("out", plate, content)

    cloud_path = None
    if cloud_health_ok():
        cloud_path = cloud_upload_image("/upload_image_out", local_path, plate, gate)

    return {
        "ok": True,
        "local_path": local_path,
        "path": cloud_path or f"local:{local_path}"
    }


@app.get("/view_image")
def view_image(path: str):
    """
    Xem ảnh local ngay tại gate:
    - path có thể là 'local:/abs/path.jpg' hoặc '/abs/path.jpg'
    """
    p = path
    if p.startswith("local:"):
        p = p.replace("local:", "", 1)

    if not os.path.isabs(p):
        # nếu người dùng gửi relative, ép về BASE_DIR
        p = os.path.join(BASE_DIR, p)

    if not os.path.exists(p):
        return {"ok": False, "msg": "Image not found", "path": path}

    return FileResponse(p, media_type="image/jpeg")


# ==========================================================
# API: VEHICLE IN/OUT (LOCAL FIRST -> CLOUD LATER)
# ==========================================================
@app.post("/vehicle_in")
async def vehicle_in(req: dict = Body(...)):
    """
    Chuẩn offline:
    1) Update LOCAL slots_local ngay (UI thấy luôn)
    2) Enqueue event (pending)
    3) Try push cloud (nếu ok -> done)
    4) WS sync_event best-effort
    """
    plate = (req.get("plate") or "").strip().upper()
    slot = (req.get("slot") or "").strip().upper()
    gate = (req.get("gate") or GATE_ID).strip().upper()
    img_in = req.get("img_in")  # có thể là cloud path hoặc local:path

    if not plate or not slot:
        return {"ok": False, "msg": "Missing plate/slot"}

    # 0) Validate local slot exists (nếu chưa có snapshot thì vẫn cho, nhưng UI thường đã có)
    s = get_slot_local(slot)
    if not s:
        # tạo slot local tối thiểu để không crash
        conn = _db()
        cur = conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO slots_local(slotid, occupied, plate, version, last_cloud_sync_at)
            VALUES(?,0,NULL,0,NULL)
        """, (slot,))
        conn.commit()
        conn.close()

    # 1) Update local state FIRST
    update_slot_local(slot, True, plate)

    # 2) Build event payload
    payload = {
        "event_id": str(uuid.uuid4()),
        "type": "vehicle_in",
        "plate": plate,
        "slot": slot,
        "gate": gate,
        "img_in": img_in,
        "ts": int(time.time() * 1000)
    }
    enqueue_event("vehicle_in", payload)

    # 3) Try push cloud now (best-effort)
    pushed = False
    if cloud_health_ok():
        # nếu img_in là local:* -> upload ảnh trước
        if isinstance(payload.get("img_in"), str) and payload["img_in"].startswith("local:"):
            local_path = payload["img_in"].replace("local:", "", 1)
            cloud_path = cloud_upload_image("/upload_image_in", local_path, plate, gate)
            if cloud_path:
                payload["img_in"] = cloud_path

        try:
            res = cloud_post_json("/vehicle_in", {
                "plate": plate,
                "slot": slot,
                "gate": gate,
                "img_in": payload.get("img_in")
            })
            if res.get("ok") is True:
                mark_event_done(payload["event_id"])
                pushed = True
        except Exception:
            pass

    # 4) WS notify best-effort
    try:
        await send_event({"type": "sync_event", "event": payload})
    except Exception:
        pass

    return {
        "ok": True,
        "local_applied": True,
        "cloud_pushed": pushed,
        "event_id": payload["event_id"]
    }


@app.post("/vehicle_out")
async def vehicle_out(req: dict = Body(...)):
    """
    Chuẩn offline:
    1) Update LOCAL slots_local ngay (UI thấy luôn)
    2) Enqueue event (pending)
    3) Try push cloud (nếu ok -> done)
    4) WS sync_event best-effort
    """
    plate = (req.get("plate") or "").strip().upper()
    gate = (req.get("gate") or GATE_ID).strip().upper()
    img_out = req.get("img_out")

    if not plate:
        return {"ok": False, "msg": "Missing plate"}

    # tìm slot đang chứa plate trong local
    slots = list_slots_local()
    current = None
    for s in slots:
        if int(s.get("occupied") or 0) == 1 and (s.get("plate") or "").upper() == plate:
            current = s
            break

    if not current:
        # vẫn cho phép tạo event "vehicle_out" để sync cloud (nếu cloud có)
        # nhưng local không biết slot -> UI không đổi slot (bạn có thể show warning)
        slotid = None
    else:
        slotid = current["slotid"]
        # 1) Update local state FIRST
        update_slot_local(slotid, False, None)

    payload = {
        "event_id": str(uuid.uuid4()),
        "type": "vehicle_out",
        "plate": plate,
        "slot": slotid,
        "gate": gate,
        "img_out": img_out,
        "ts": int(time.time() * 1000)
    }
    enqueue_event("vehicle_out", payload)

    pushed = False
    if cloud_health_ok():
        # nếu img_out là local:* -> upload ảnh trước
        if isinstance(payload.get("img_out"), str) and payload["img_out"].startswith("local:"):
            local_path = payload["img_out"].replace("local:", "", 1)
            cloud_path = cloud_upload_image("/upload_image_out", local_path, plate, gate)
            if cloud_path:
                payload["img_out"] = cloud_path

        try:
            res = cloud_post_json("/vehicle_out", {
                "plate": plate,
                "gate": gate,
                "img_out": payload.get("img_out")
            })
            if res.get("ok") is True:
                mark_event_done(payload["event_id"])
                pushed = True
        except Exception:
            pass

    try:
        await send_event({"type": "sync_event", "event": payload})
    except Exception:
        pass

    return {
        "ok": True,
        "local_applied": True,
        "cloud_pushed": pushed,
        "event_id": payload["event_id"],
        "slot": slotid
    }


# ==========================================================
# HEALTH
# ==========================================================
@app.get("/health")
def health():
    return {
        "ok": True,
        "gate": GATE_ID,
        "cloud_api": CLOUD_API,
        "last_cloud_ok_at": get_state("last_cloud_ok_at"),
        "time": datetime.utcnow().isoformat() + "Z"
    }


# ==========================================================
# BACKGROUND WORKERS (SYNC SNAPSHOT + SYNC QUEUE)
# ==========================================================
async def worker_sync_cloud_snapshot():
    """
    Nếu Cloud ON:
      - kéo /slots/map từ Cloud
      - upsert vào slots_local
    """
    await asyncio.sleep(2)
    while True:
        try:
            if cloud_health_ok():
                r = requests.get(f"{CLOUD_API}/slots/map", timeout=5)
                j = r.json()
                if isinstance(j, dict) and "slots" in j:
                    upsert_slots_from_cloud(j["slots"])
        except Exception:
            pass

        await asyncio.sleep(3)  # bạn chỉnh 2-5s tùy demo


async def worker_sync_event_queue():
    """
    Nếu Cloud ON:
      - lấy pending events
      - upload ảnh local (nếu cần)
      - gọi cloud /vehicle_in hoặc /vehicle_out
      - done nếu ok
    """
    await asyncio.sleep(3)
    while True:
        try:
            if not cloud_health_ok():
                await asyncio.sleep(2)
                continue

            pending = get_pending_events(limit=50)
            for item in pending:
                event_id = item["event_id"]
                et = item["event_type"]
                p = item["payload"]

                if et == "vehicle_in":
                    plate = p.get("plate")
                    slot = p.get("slot")
                    gate = p.get("gate") or GATE_ID
                    img_in = p.get("img_in")

                    # upload ảnh nếu local
                    if isinstance(img_in, str) and img_in.startswith("local:"):
                        local_path = img_in.replace("local:", "", 1)
                        cloud_path = cloud_upload_image("/upload_image_in", local_path, plate, gate)
                        if cloud_path:
                            p["img_in"] = cloud_path

                    res = cloud_post_json("/vehicle_in", {
                        "plate": plate,
                        "slot": slot,
                        "gate": gate,
                        "img_in": p.get("img_in")
                    })
                    if res.get("ok") is True:
                        mark_event_done(event_id)

                elif et == "vehicle_out":
                    plate = p.get("plate")
                    gate = p.get("gate") or GATE_ID
                    img_out = p.get("img_out")

                    if isinstance(img_out, str) and img_out.startswith("local:"):
                        local_path = img_out.replace("local:", "", 1)
                        cloud_path = cloud_upload_image("/upload_image_out", local_path, plate, gate)
                        if cloud_path:
                            p["img_out"] = cloud_path

                    res = cloud_post_json("/vehicle_out", {
                        "plate": plate,
                        "gate": gate,
                        "img_out": p.get("img_out")
                    })
                    if res.get("ok") is True:
                        mark_event_done(event_id)

                # best-effort WS replay (không bắt buộc)
                try:
                    await send_event({"type": "sync_event", "event": p})
                except Exception:
                    pass

        except Exception:
            pass

        await asyncio.sleep(2)


def start_background_loop():
    """
    Chạy 2 worker async trong 1 loop riêng (thread daemon),
    tránh phụ thuộc vào uvicorn loop và tránh block.
    """
    loop = asyncio.new_event_loop()

    def runner():
        asyncio.set_event_loop(loop)
        tasks = [
            worker_sync_cloud_snapshot(),
            worker_sync_event_queue(),
        ]
        loop.run_until_complete(asyncio.gather(*tasks))

    t = threading.Thread(target=runner, daemon=True)
    t.start()


start_background_loop()
