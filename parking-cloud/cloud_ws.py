from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import os
import time
import psycopg2

ws_router = APIRouter()
active_gates = {}   # gateid -> websocket

POSTGRES_DB   = os.getenv("POSTGRES_DB", "parking")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASS = os.getenv("POSTGRES_PASSWORD", "admin")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))

def _update_gate_last_sync(gateid: str):
    try:
        conn = psycopg2.connect(
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASS,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
        )
        cur = conn.cursor()
        cur.execute("""
            UPDATE gates
            SET last_sync = (SELECT NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
            WHERE gateid=%s
        """, (gateid,))
        conn.commit()
        cur.close()
        conn.close()
    except:
        pass

async def broadcast_all(message: dict):
    dead = []
    for gid, ws in active_gates.items():
        try:
            await ws.send_text(json.dumps(message))
        except:
            dead.append(gid)

    for gid in dead:
        active_gates.pop(gid, None)

@ws_router.websocket("/ws/gate/{gateid}")
async def ws_gate(websocket: WebSocket, gateid: str):
    await websocket.accept()
    active_gates[gateid] = websocket
    print(f"[WS] Gate {gateid} connected")

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            et = data.get("type")

            if et == "heartbeat":
                _update_gate_last_sync(gateid)
                await broadcast_all({"type": "heartbeat", "gate": gateid})
                continue

            if et == "ping":
                await websocket.send_text(json.dumps({
                    "type": "pong",
                    "gate": gateid,
                    "ts": data.get("ts"),
                    "server_ts": int(time.time() * 1000),
                }))
                continue

            if et == "sync_event":
                evt = data.get("event")
                if evt:
                    await broadcast_all(evt)
                continue

            print(f"[WS] Unknown event from {gateid}:", data)

    except WebSocketDisconnect:
        print(f"[WS] Gate {gateid} disconnected")
        active_gates.pop(gateid, None)
    except Exception as e:
        print(f"[WS] Error gate {gateid}:", e)
        active_gates.pop(gateid, None)
