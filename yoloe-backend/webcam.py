import os, time
import cv2
import torch
from ultralytics import YOLO

MODEL = os.environ.get("YOLOE_MODEL", "yolov8n.pt")
CONF  = float(os.environ.get("YOLOE_CONF", 0.25))
IOU   = float(os.environ.get("YOLOE_IOU", 0.45))
DEVICE = os.environ.get("YOLOE_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

model = YOLO(MODEL).to(DEVICE)
model.fuse()

# 0 = default laptop cam; try 1/2 if you have multiple
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    raise SystemExit("Could not open webcam. Try a different index (1, 2) or grant camera permission.")

while True:
    ok, frame = cap.read()
    if not ok: 
        break

    # Inference (BGR frame is fine)
    results = model(frame, conf=CONF, iou=IOU, device=DEVICE, verbose=False)[0]

    # Draw boxes
    if results.boxes is not None and len(results.boxes) > 0:
        names = getattr(model, "names", {})
        for xyxy, c, k in zip(results.boxes.xyxy, results.boxes.conf, results.boxes.cls):
            x1, y1, x2, y2 = map(int, xyxy.tolist())
            cls_name = names.get(int(k), str(int(k)))
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"{cls_name} {float(c):.2f}", (x1, max(0, y1-5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    cv2.imshow("YOLOE Webcam (press q to quit)", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
