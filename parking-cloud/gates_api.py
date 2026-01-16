import os, asyncio, time
import redis, orjson, psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import pytz

from fastapi import FastAPI, Body, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from cloud_ws import ws_router, broadcast_all  # ⭐ WS broadcast realtime

# ======================================================
# INIT FASTAPI
# ======================================================
app = FastAPI(title="Parking Cloud API (Distributed Mode)")
app.include_router(ws_router)   # WS server

# ======================================================
# TIMEZONE
# ======================================================
TZ = pytz.timezone("Asia/Ho_Chi_Minh")

# ======================================================
# DATABASE CONFIG
# ======================================================


POSTGRES_DB   = os.getenv("POSTGRES_DB", "parking")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASS = os.getenv("POSTGRES_PASSWORD", "admin")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "secret-key")

os.makedirs("images/in", exist_ok=True)
os.makedirs("images/out", exist_ok=True)

def get_conn():
    return psycopg2.connect(
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASS,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        cursor_factory=RealDictCursor
    )

def get_redis():
    for _ in range(5):
        try:
            return redis.Redis.from_url(REDIS_URL, decode_responses=True)
        except:
            time.sleep(1)
    raise Exception("Redis connect failed")

r = get_redis()

# ======================================================
# BROADCAST EVENT
# ======================================================
# ======================================================
# BROADCAST EVENT (SAFE FOR SYNC + ASYNC)
# ======================================================
import threading

def run_ws(event: dict):
    try:
        asyncio.run(broadcast_all(event))
    except:
        pass

def broadcast(event: dict):
    """
    Redis PubSub + WS broadcast (safe cho sync/async endpoint)
    """
    # Redis
    try:
        r.publish("parking:events", orjson.dumps(event).decode())
    except:
        pass

    # WS
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_all(event))
    except RuntimeError:
        threading.Thread(target=run_ws, args=(event,), daemon=True).start()


# ======================================================
# CORS
# ======================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ======================================================
# AUTH MIDDLEWARE
# ======================================================
PUBLIC_PATHS = (
    "/login",
    "/health",
    "/ws",
    "/images",
    "/view_image",
    "/upload_image_in",
    "/upload_image_out",
    "/transactions",
    "/slot_info",
     "/slots/map",
     "/payments/vietqr",

)

def verify_token(auth: str | None):
    if not auth:
        raise HTTPException(401, "Unauthorized")

    token = auth.replace("Bearer", "").strip()
    if token != SECRET_TOKEN:
        raise HTTPException(401, "Unauthorized")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    if any(path.startswith(p) for p in PUBLIC_PATHS):
        return await call_next(request)

    try:
        verify_token(request.headers.get("Authorization"))
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})

    return await call_next(request)


# ======================================================
# HEALTH
# ======================================================
@app.get("/health")
def health():
    return {"ok": True, "time": datetime.now(TZ).isoformat()}


# ======================================================
# LOGIN
# ======================================================
@app.post("/login")
def login(data: dict = Body(...)):
    user = data.get("username")
    pw = data.get("password")

    if not user or not pw:
        raise HTTPException(400, "Missing login info")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT username, gateid, role 
        FROM users 
        WHERE username=%s AND password=%s
    """, (user, pw))

    row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(401, "Invalid username/password")

    return {
        "ok": True,
        "username": row["username"],
        "gateid": row["gateid"],
        "role": row["role"],
        "token": SECRET_TOKEN
    }


# ======================================================
# GATES
# ======================================================
@app.get("/gates")
def list_gates():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM gates ORDER BY gateid")
    rows = cur.fetchall()
    conn.close()

    now = datetime.now(TZ)
    for g in rows:
        g["online"] = (now - g["last_sync"]) < timedelta(seconds=60) if g["last_sync"] else False

    return {"gates": rows}


@app.post("/heartbeat")
def heartbeat(data: dict = Body(...)):
    gateid = data.get("gateid")
    if not gateid:
        raise HTTPException(400, "missing gateid")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE gates 
        SET last_sync = (SELECT NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
        WHERE gateid=%s
    """, (gateid,))
    conn.commit()
    conn.close()

    broadcast({"type": "heartbeat", "gate": gateid})
    return {"ok": True}


# ======================================================
# RESERVE SLOT (COORDINATION TTL) — HƯỚNG 3
# ======================================================
@app.post("/reserve_slot")
def reserve_slot(data: dict = Body(...), request: Request = None):
    # auth middleware đã bảo vệ route này (không nằm trong PUBLIC_PATHS)

    gate = (data.get("gate") or "").strip().upper()
    slot = (data.get("slot") or "").strip().upper()
    ttl  = int(data.get("ttl", 15))

    if not gate or not slot:
        raise HTTPException(400, "missing gate/slot")

    key = f"reserve:{slot}"
    owner = r.get(key)

    if owner and owner != gate:
        raise HTTPException(409, f"Slot {slot} đang được giữ bởi gate {owner}")

    r.setex(key, ttl, gate)
    return {"ok": True, "slot": slot, "gate": gate, "ttl": ttl}


@app.get("/reserve_slot/{slotid}")
def get_reserve(slotid: str):
    slotid = slotid.strip().upper()
    key = f"reserve:{slotid}"
    owner = r.get(key)
    ttl = r.ttl(key) if owner else -1
    return {"ok": True, "slot": slotid, "gate": owner, "ttl": ttl}

# ======================================================
# SLOTS
# ======================================================
import math
from fastapi import Query, HTTPException




@app.put("/slots/{slotid}")
def update_slot(slotid: str, body: dict = Body(...)):
    occupied = bool(body.get("occupied", False))
    plate = body.get("plate") or None

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE slots 
        SET occupied=%s, plate=%s, version=version+1
        WHERE slotid=%s
    """, (occupied, plate, slotid))
    conn.commit()
    conn.close()

    broadcast({"type": "slot_update", "slotId": slotid, "occupied": occupied, "plate": plate})
    return {"msg": "ok"}

import psycopg2.errors

def ensure_event_once(cur, conn, event_id: str | None, event_type: str, gate: str):
    """
    Return True nếu event mới (chưa xử lý)
    Return False nếu event đã xử lý rồi (dedup)
    """
    if not event_id:
        return True  # không có event_id thì không dedup được

    try:
        cur.execute(
            "INSERT INTO processed_events(event_id, event_type, gateid) VALUES (%s,%s,%s)",
            (event_id, event_type, gate)
        )
        return True
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return False


# ======================================================
# VEHICLE IN
# ======================================================
from fastapi import Body, HTTPException
from datetime import datetime
import pytz

TZ = pytz.timezone("Asia/Ho_Chi_Minh")

# ======================================================
# VEHICLE IN (IDEMPOTENT + TRANSACTION)
# ======================================================
@app.post("/vehicle_in")
def vehicle_in(data: dict = Body(...)):
    plate = (data.get("plate") or "").strip().upper()
    gate  = (data.get("gate") or "").strip().upper()
    slot  = (data.get("slot") or "").strip().upper()
    img_in = data.get("img_in")
    event_id = (data.get("event_id") or "").strip()  # ✅ NEW: để dedup

    if not plate or not gate or not slot:
        raise HTTPException(400, "missing plate/gate/slot")

    conn = get_conn()
    try:
        # ✅ dùng transaction context: lỗi là rollback, ok thì commit
        with conn:
            cur = conn.cursor()

            # ✅ 0) DEDUP (idempotent)
            if event_id:
                cur.execute("SELECT 1 FROM processed_events WHERE event_id=%s", (event_id,))
                if cur.fetchone():
                    return {"ok": True, "dedup": True}

            # 1) gate exists?
            cur.execute("SELECT 1 FROM gates WHERE gateid=%s", (gate,))
            if not cur.fetchone():
                raise HTTPException(404, "Gate không tồn tại")

            # 2) slot valid?
            cur.execute("SELECT occupied FROM slots WHERE slotid=%s", (slot,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Slot không tồn tại")

            # 3) conflict slot occupied
            if row["occupied"]:
                raise HTTPException(409, f"Slot {slot} đã có xe")

            # 4) conflict plate already in yard
            cur.execute("""
                SELECT 1 FROM vehicles
                WHERE plate=%s AND time_out IS NULL
                LIMIT 1
            """, (plate,))
            if cur.fetchone():
                raise HTTPException(409, f"Xe {plate} đang ở trong bãi")

            # 5) conflict reserve by other gate
            key = f"reserve:{slot}"
            owner = r.get(key)
            if owner and owner != gate:
                raise HTTPException(409, f"Slot {slot} đang được giữ bởi gate {owner}")

            # 6) update slot
            cur.execute("""
                UPDATE slots
                SET occupied=true, plate=%s, version=version+1
                WHERE slotid=%s
            """, (plate, slot))

            # 7) insert vehicles
            cur.execute("""
                INSERT INTO vehicles (plate, slotid, gateid, source_gate, time_in)
                VALUES (%s, %s, %s, %s, (SELECT NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh'))
            """, (plate, slot, gate, gate))

            # 8) insert transactions
            cur.execute("""
                INSERT INTO transactions (plate, slotid, gateid, time_in, img_in)
                VALUES (%s, %s, %s, (SELECT NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh'), %s)
            """, (plate, slot, gate, img_in))

            # ✅ 9) mark processed event
            if event_id:
                cur.execute("""
                    INSERT INTO processed_events(event_id, gateid, event_type)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                """, (event_id, gate, "vehicle_in"))

        # ngoài transaction: clear reserve + broadcast
        try:
            r.delete(f"reserve:{slot}")
        except:
            pass

        broadcast({"type": "slot_update", "slotId": slot, "occupied": True, "plate": plate})
        broadcast({"type": "vehicle_in", "plate": plate, "slot": slot, "gate": gate})

        return {"ok": True}

    finally:
        conn.close()


# ======================================================
# VEHICLE OUT (IDEMPOTENT + FIX UPDATE TRANSACTIONS)
# ======================================================
@app.post("/vehicle_out")
def vehicle_out(data: dict = Body(...)):
    plate = (data.get("plate") or "").strip().upper()
    gate  = (data.get("gate") or "").strip().upper() or None
    img_out = data.get("img_out")
    event_id = (data.get("event_id") or "").strip()  # ✅ dedup

    if not plate:
        raise HTTPException(400, "missing plate")

    conn = get_conn()
    try:
        with conn:
            cur = conn.cursor()

            # ✅ 0) DEDUP
            if event_id:
                cur.execute("SELECT 1 FROM processed_events WHERE event_id=%s", (event_id,))
                if cur.fetchone():
                    return {"ok": True, "dedup": True}

            # 1) find current vehicle in yard
            cur.execute("""
                SELECT id, slotid, time_in
                FROM vehicles
                WHERE plate=%s AND time_out IS NULL
                ORDER BY time_in DESC
                LIMIT 1
            """, (plate,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "Xe không tồn tại trong bãi")

            slotid = row["slotid"]
            time_in = row["time_in"]

            # tz aware
            if getattr(time_in, "tzinfo", None) is None:
                time_in = TZ.localize(time_in)

            time_out = datetime.now(TZ)
            fee, duration = calc_fee(time_in, time_out)

            # 2) free slot
            cur.execute("""
                UPDATE slots
                SET occupied=false, plate=NULL, version=version+1
                WHERE slotid=%s
            """, (slotid,))

            # 3) close vehicles
            cur.execute("""
                UPDATE vehicles
                SET time_out=%s
                WHERE id=%s
            """, (time_out, row["id"]))

            # ✅ 4) FIX transactions: schema dùng trans_id (không phải id)
            cur.execute("""
                SELECT trans_id
                FROM transactions
                WHERE plate=%s AND time_out IS NULL
                ORDER BY time_in DESC
                LIMIT 1
            """, (plate,))
            trow = cur.fetchone()
            if not trow:
                raise HTTPException(404, "Không tìm thấy transaction đang mở")

            tx_id = trow["trans_id"]

            cur.execute("""
                UPDATE transactions
                SET time_out=%s,
                    duration_minutes=%s,
                    fee=%s,
                    img_out=%s
                WHERE trans_id=%s
            """, (time_out, duration, fee, img_out, tx_id))

            # 5) mark processed
            if event_id:
                cur.execute("""
                    INSERT INTO processed_events(event_id, gateid, event_type)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                """, (event_id, gate, "vehicle_out"))

        # outside transaction
        broadcast({"type": "slot_update", "slotId": slotid, "occupied": False, "plate": None})
        broadcast({"type": "vehicle_out", "plate": plate, "slot": slotid, "gate": gate})

        return {"ok": True, "duration_minutes": duration, "fee": fee, "slot": slotid}

    finally:
        conn.close()

# ======================================================
# FEE CALCULATOR
# ======================================================
def calc_fee(time_in, time_out):
    delta = time_out - time_in
    minutes = int(delta.total_seconds() // 60)
    hours = (minutes // 60) + (1 if minutes % 60 > 0 else 0)
    if hours <= 1:
        return 5000, minutes
    return 5000 + (hours - 1) * 3000, minutes


# ======================================================
# IMAGE UPLOAD
# ======================================================
@app.post("/upload_image_in")
async def upload_image_in(
    plate: str = Form(...),
    gate: str = Form(...),
    file: UploadFile = File(...)
):
    filename = f"{plate}_{int(time.time())}.jpg"
    path = f"images/in/{filename}"

    with open(path, "wb") as f:
        f.write(await file.read())

    return {"ok": True, "path": path}


@app.post("/upload_image_out")
async def upload_image_out(
    plate: str = Form(...),
    gate: str = Form(...),
    file: UploadFile = File(...)
):
    filename = f"{plate}_{int(time.time())}.jpg"
    path = f"images/out/{filename}"

    with open(path, "wb") as f:
        f.write(await file.read())

    return {"ok": True, "path": path}




@app.get("/view_image")
def view_image(path: str):
    full = path if path.startswith("images/") else os.path.join("images", path)

    if not os.path.exists(full):
        raise HTTPException(404, "Image not found")

    return FileResponse(full, media_type="image/jpeg")


# ======================================================
# STATIC
# ======================================================
app.mount("/images", StaticFiles(directory="images"), name="images")

# ======================================================
# GET TRANSACTIONS (LỊCH SỬ XE VÀO / RA)
# ======================================================
import uuid
from fastapi import Query
@app.get("/transactions")
def list_transactions():
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT trans_id, plate, slotid, gateid,
                   time_in, time_out, duration_minutes,
                   fee, img_in, img_out, payment_id
            FROM transactions
            ORDER BY time_in DESC
        """)
        rows = cur.fetchall()
        return {"ok": True, "transactions": rows}
    finally:
        conn.close()


@app.get("/slot_info/{slotid}")
def slot_info(slotid: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT v.*, t.img_in, t.img_out
        FROM vehicles v
        LEFT JOIN transactions t ON t.plate = v.plate AND t.time_out IS NULL
        WHERE v.slotid=%s AND v.time_out IS NULL
        ORDER BY v.time_in DESC LIMIT 1
    """, (slotid,))
    
    row = cur.fetchone()
    conn.close()

    return {"info": row}

@app.get("/suggest_slot/{gateid}")
def suggest_slot(gateid: str):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT x, y FROM gates WHERE gateid=%s", (gateid,))
    gate = cur.fetchone()
    if not gate:
        conn.close()
        raise HTTPException(404, "Gate không tồn tại")

    gx, gy = gate["x"], gate["y"]

    cur.execute("""
        SELECT slotid, x, y
        FROM slots
        WHERE occupied=false
          AND x IS NOT NULL
          AND y IS NOT NULL
    """)
    slots = cur.fetchall()
    conn.close()

    if not slots:
        return {"slot": None, "distance": None}

    def dist(s):
        return math.sqrt(
            (s["x"] - gx) ** 2 +
            (s["y"] - gy) ** 2
        )

    best = min(slots, key=dist)

    return {
        "slot": best["slotid"],
        "distance": round(dist(best), 2),
        "gate": gateid
    }


@app.get("/slots/map")
def get_slots_map():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT slotid, zone, x, y, occupied, plate, version
        FROM slots
        ORDER BY slotid
    """)
    rows = cur.fetchall()
    conn.close()

    return {"slots": rows}



@app.get("/slots")
def get_slots(gate_id: str = Query(...)):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT x, y FROM gates WHERE gateid=%s", (gate_id,))
    gate = cur.fetchone()
    gx, gy = gate["x"], gate["y"]

    cur.execute("""
        SELECT slotid, zone, x, y, occupied, plate, version
        FROM slots
    """)
    slots = cur.fetchall()
    conn.close()

    result = []
    for s in slots:
        dist = math.sqrt((s["x"] - gx)**2 + (s["y"] - gy)**2)

        result.append({
            "slotid": s["slotid"],
            "zone": s["zone"],
            "x": s["x"],
            "y": s["y"],
            "occupied": s["occupied"],
            "plate": s["plate"],
            "version": s["version"],
            "distance": round(dist, 2)
        })

    result.sort(key=lambda x: x["distance"])
    return {"slots": result}

from fastapi import Header, HTTPException
from fastapi import Depends
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db():
    conn = psycopg2.connect(
        host="postgres",
        dbname="parking",
        user="admin",
        password="admin",
        port=5432
    )
    cur = conn.cursor(cursor_factory=RealDictCursor)
    return conn, cur

def admin_auth(authorization: str = Header(None)):
    if authorization != "Bearer secret-key":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

    
@app.put("/admin/slots/{slotid}")
def admin_update_slot(slotid: str, data: dict, user=Depends(admin_auth)):
    conn, cur = get_db()

    cur.execute("""
        UPDATE slots
        SET x=%s, y=%s, zone=%s
        WHERE slotid=%s
    """, (data["x"], data["y"], data["zone"], slotid))

    conn.commit()
    cur.close()
    conn.close()

    return {"ok": True}



@app.post("/admin/slots")
def admin_add_slot(slot: dict, user=Depends(admin_auth)):
    conn, cur = get_db()   # ⭐ BẮT BUỘC

    cur.execute("""
        INSERT INTO slots(slotid, zone, x, y, occupied)
        VALUES (%s, %s, %s, %s, false)
    """, (slot["slotid"], slot["zone"], slot["x"], slot["y"]))

    conn.commit()
    cur.close()
    conn.close()

    return {"ok": True}


@app.delete("/admin/slots/{slotid}")
def admin_delete_slot(slotid: str, user=Depends(admin_auth)):
    conn, cur = get_db()

    cur.execute("SELECT occupied FROM slots WHERE slotid=%s", (slotid,))
    row = cur.fetchone()

    if row and row["occupied"]:
        cur.close()
        conn.close()
        raise HTTPException(409, "Slot đang có xe")

    cur.execute("DELETE FROM slots WHERE slotid=%s", (slotid,))
    conn.commit()

    cur.close()
    conn.close()

    return {"ok": True}

@app.get("/fee")
def fee(plate: str = Query(...), gate: str = Query(default="")):
    plate = plate.strip().upper()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT trans_id, time_in, slotid, gateid
            FROM transactions
            WHERE plate=%s AND time_out IS NULL
            ORDER BY time_in DESC
            LIMIT 1
        """, (plate,))
        t = cur.fetchone()
        if not t:
            raise HTTPException(404, "Không tìm thấy xe đang trong bãi")

        time_in = t["time_in"]
        if getattr(time_in, "tzinfo", None) is None:
            time_in = TZ.localize(time_in)

        time_out = datetime.now(TZ)
        fee_value, duration_minutes = calc_fee(time_in, time_out)

        hours = max(1, (duration_minutes + 59) // 60)
        duration_text = f"{hours} giờ ({duration_minutes} phút)"

        return {
            "ok": True,
            "plate": plate,
            "slot": t["slotid"],
            "gate": t["gateid"],
            "time_in": time_in.isoformat(),
            "time_out": time_out.isoformat(),
            "duration_minutes": duration_minutes,
            "duration_text": duration_text,
            "amount": fee_value,
            "trans_id": t["trans_id"]
        }
    finally:
        conn.close()


import io
import urllib.parse
import qrcode
from fastapi import Body, HTTPException
from fastapi.responses import Response

BANK_INFO = {
    "bank_code": "MB",            # ✅ BẮT BUỘC cho VietQR
    "bank_name": "MBBANK",
    "account_no": "4506120217",
    "account_name": "NGUYEN THANH THINH"
}

def make_vietqr_url(bank_code: str, account_no: str, amount: int, add_info: str, account_name: str = ""):
    # URL chuẩn VietQR (dạng ảnh). App bank quét QR sẽ hiểu chuyển khoản.
    base = f"https://img.vietqr.io/image/{bank_code}-{account_no}-compact2.png"
    qs = urllib.parse.urlencode({
        "amount": amount,
        "addInfo": add_info,
        "accountName": account_name
    })
    return f"{base}?{qs}"

@app.post("/payments/vietqr/create")
def payment_vietqr_create(data: dict = Body(...)):
    import uuid

    plate = (data.get("plate") or "").strip().upper()
    gate  = (data.get("gate") or "").strip().upper() or None
    amount = int(data.get("amount") or 0)

    if not plate or amount <= 0:
        raise HTTPException(400, "missing plate/amount")

    payment_id = str(uuid.uuid4())
    transfer_content = f"PARK-{payment_id[:8].upper()}"

    # lưu payment PENDING
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO payments(payment_id, plate, gateid, amount, method, status, transfer_content)
            VALUES (%s::uuid, %s, %s, %s, 'vietqr', 'PENDING', %s)
        """, (payment_id, plate, gate, amount, transfer_content))
        conn.commit()
    finally:
        conn.close()

    vietqr_url = make_vietqr_url(
        BANK_INFO["bank_code"],
        BANK_INFO["account_no"],
        amount,
        transfer_content,
        BANK_INFO["account_name"]
    )

    return {
        "ok": True,
        "payment_id": payment_id,
        "amount": amount,
        "transfer_content": transfer_content,
        "bank_info": BANK_INFO,
        "vietqr_url": vietqr_url,   # UI có thể dùng để show text/preview
        "status": "PENDING"
    }

@app.get("/payments/vietqr/{payment_id}.png")
def payment_vietqr_png(payment_id: str, amount: int, addInfo: str, bank: str = "VCB", acc: str = "0123456789", name: str = "PARKING DEMO"):
    # Trả về ảnh PNG QR để UI load trực tiếp
    vietqr_url = make_vietqr_url(bank, acc, int(amount), addInfo, name)

    qr = qrcode.QRCode(border=2)
    qr.add_data(vietqr_url)
    qr.make(fit=True)
    img = qr.make_image()  # PIL image

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")

import uuid
from fastapi import Body, HTTPException



@app.post("/payments/manual/create")
def payment_manual_create(data: dict = Body(...)):
    plate = (data.get("plate") or "").strip().upper()
    gate  = (data.get("gate") or "").strip().upper() or None
    amount = int(data.get("amount") or 0)

    if not plate or amount <= 0:
        raise HTTPException(400, "missing plate/amount")

    pid_str = str(uuid.uuid4())          # ✅ string
    transfer_content = f"PARK-{pid_str[:8].upper()}"

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO payments(payment_id, plate, gateid, amount, method, status, transfer_content)
            VALUES (%s::uuid, %s, %s, %s, 'online_manual', 'PENDING', %s)
        """, (pid_str, plate, gate, amount, transfer_content))
        conn.commit()

        return {
            "ok": True,
            "payment_id": pid_str,
            "bank_info": BANK_INFO,
            "transfer_content": transfer_content,
            "status": "PENDING"
        }
    finally:
        conn.close()

@app.post("/payments/manual/confirm")
def payment_manual_confirm(data: dict = Body(...)):
    pid = data.get("payment_id")
    pid_str = str(pid).strip() if pid is not None else ""
    if not pid_str:
        raise HTTPException(400, "missing payment_id")

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE payments
            SET status='PAID',
                paid_at=(SELECT NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
            WHERE payment_id=%s::uuid
        """, (pid_str,))
        if cur.rowcount == 0:
            raise HTTPException(404, "payment not found")
        conn.commit()
        return {"ok": True, "payment_id": pid_str, "status": "PAID"}
    finally:
        conn.close()

@app.post("/payments/cash/confirm")
def payment_cash_confirm(data: dict = Body(...)):
    plate = (data.get("plate") or "").strip().upper()
    gate  = (data.get("gate") or "").strip().upper() or None
    amount = int(data.get("amount") or 0)
    if not plate or amount <= 0:
        raise HTTPException(400, "missing plate/amount")

    pid_str = str(uuid.uuid4())

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO payments(payment_id, plate, gateid, amount, method, status, paid_at)
            VALUES (%s::uuid, %s, %s, %s, 'cash', 'PAID',
                    (SELECT NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh'))
        """, (pid_str, plate, gate, amount))
        conn.commit()
        return {"ok": True, "payment_id": pid_str, "status": "PAID"}
    finally:
        conn.close()

from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    )
