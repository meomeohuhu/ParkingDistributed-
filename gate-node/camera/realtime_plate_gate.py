import cv2
from ultralytics import YOLO
import easyocr
import requests
import time
import torch
from ultralytics.nn.tasks import DetectionModel
torch.serialization.add_safe_globals([DetectionModel])

MODEL_PATH = "best.pt"
GATE_API = "http://localhost:8000"
GATE_ID = "G_N"
SEND_INTERVAL = 3
MIN_PLATE_SIZE = 80

print("▶ Loading YOLO...")
model = YOLO(MODEL_PATH)

print("▶ Loading OCR...")
ocr = easyocr.Reader(['en'], gpu=False)

print("▶ Starting camera...")
cap = cv2.VideoCapture(0)
last_send = 0


# ===========================
# OCR BIỂN SỐ 2 DÒNG
# ===========================
def read_plate_two_lines(crop):
    h, w, _ = crop.shape
    if h < 20:
        return ""

    mid = h // 2
    top = crop[0:mid, :]
    bottom = crop[mid:h, :]

    t1 = ocr.readtext(top, detail=0)
    t2 = ocr.readtext(bottom, detail=0)

    line1 = t1[0] if len(t1) else ""
    line2 = t2[0] if len(t2) else ""

    return (line1 + line2).replace(" ", "").upper()


# ===========================
# UPLOAD IMAGE TO GATE
# ===========================
def upload_image_to_gate(frame, plate):
    _, jpg = cv2.imencode(".jpg", frame)
    files = {"file": ("plate.jpg", jpg.tobytes(), "image/jpeg")}
    data = {"plate": plate, "gate": GATE_ID}

    try:
        r = requests.post(f"{GATE_API}/upload_image_in", files=files, data=data, timeout=5)
        return r.json().get("path")
    except Exception as e:
        print("❌ Upload lỗi:", e)
        return None


# ===========================
# SEND VEHICLE IN WITH IMAGE
# ===========================
def send_vehicle_in(plate, img_path):
    try:
        r = requests.post(
            f"{GATE_API}/vehicle_in",
            json={"plate": plate, "gate": GATE_ID, "slot": "G1", "img_in": img_path},
            timeout=5,
        )
        print("✔ Vehicle IN:", r.json())
    except Exception as e:
        print("❌ API lỗi:", e)


# ===========================
# MAIN LOOP
# ===========================
while True:
    ret, frame = cap.read()
    if not ret:
        print("❌ Camera error")
        break

    results = model(frame)[0]

    for b in results.boxes:
        x1, y1, x2, y2 = map(int, b.xyxy[0])
        crop = frame[y1:y2, x1:x2]
        plate = read_plate_two_lines(crop)

        if len(plate) > 3 and time.time() - last_send > SEND_INTERVAL:
            last_send = time.time()

            print("▶ Uploading image...")
            img_path = upload_image_to_gate(frame, plate)

            print("▶ Sending vehicle IN...")
            send_vehicle_in(plate, img_path)

    cv2.imshow("Realtime Plate Gate", frame)
    if cv2.waitKey(1) == 27:
        break

cap.release()
cv2.destroyAllWindows()
