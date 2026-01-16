# gate_ws.py – REALTIME WS FOR DISTRIBUTED GATE NODE
import asyncio
import json
import websockets
import threading
import queue
import time
from websockets.exceptions import ConnectionClosed

WS = None
CONNECTED = False

# Queue để GUI đọc event từ WS
GUI_EVENT_QUEUE = queue.Queue()


async def ping_loop(gateid: str, interval_s: float = 5.0):
    """Gửi ping định kỳ để đo RTT (Hướng 4)."""
    global WS, CONNECTED
    while True:
        await asyncio.sleep(interval_s)
        if CONNECTED and WS:
            try:
                await WS.send(
                    json.dumps(
                        {
                            "type": "ping",
                            "gate": gateid,
                            "ts": int(time.time() * 1000),
                        }
                    )
                )
            except Exception:
                pass

# ======================================================
# GỬI HEARTBEAT LIÊN TỤC CHO CLOUD
# ======================================================
async def heartbeat(gateid: str):
    global WS, CONNECTED

    while True:
        await asyncio.sleep(4)
        if CONNECTED:
            try:
                # Gửi heartbeat theo format mà cloud_ws yêu cầu
                await WS.send(json.dumps({
                    "type": "heartbeat",
                    "gate": gateid
                }))
            except:
                pass


# ======================================================
# KẾT NỐI WS VỚI CLOUD
# ======================================================
async def connect_ws(cloud_ip: str, gateid: str):
    global WS, CONNECTED

    url = f"ws://{cloud_ip}:8010/ws/gate/{gateid}"

    while True:
        try:
            print(f"[WS] Connecting to {url} ...")

            WS = await websockets.connect(url)
            CONNECTED = True
            print("[WS] Connected!")

            # Chạy heartbeat song song
            asyncio.create_task(heartbeat(gateid))

            # Chạy ping để đo RTT
            asyncio.create_task(ping_loop(gateid))

            await listen_loop(gateid)

        except Exception as e:
            CONNECTED = False
            print("[WS] Connection failed → retry in 3s:", e)
            await asyncio.sleep(3)


# ======================================================
# LẮNG NGHE DỮ LIỆU TỪ CLOUD GỬI VỀ
# ======================================================
async def listen_loop(gateid: str):
    global WS, CONNECTED

    try:
        while True:
            msg = await WS.recv()
            data = json.loads(msg)

            # PONG: tính RTT và gửi cho GUI
            if data.get("type") == "pong" and data.get("ts") is not None:
                try:
                    rtt = int(time.time() * 1000) - int(data["ts"])
                    GUI_EVENT_QUEUE.put({"type": "rtt", "gate": gateid, "rtt_ms": rtt})
                except Exception:
                    pass
                continue

            # Tất cả event Cloud gửi (khác pong) đều đưa vào queue để GUI xử lý
            GUI_EVENT_QUEUE.put(data)

            print("[WS] Received:", data)

    except ConnectionClosed:
        print("[WS] Disconnected!")
        CONNECTED = False

    except Exception as e:
        print("[WS] WS error:", e)
        CONNECTED = False


# ======================================================
# GỬI EVENT LÊN CLOUD
# ======================================================
async def send_event(event: dict):
    global WS, CONNECTED

    if not CONNECTED:
        return False

    try:
        await WS.send(json.dumps(event))
        return True
    except:
        return False


# ======================================================
# KHỞI CHẠY WS TRONG THREAD KHÁC
# ======================================================
def start_ws(cloud_ip: str, gateid: str):
    loop = asyncio.new_event_loop()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(connect_ws(cloud_ip, gateid))

    t = threading.Thread(target=run, daemon=True)
    t.start()
