from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict
from PIL import Image
import base64, io, os
from ws_yoloe import setup_websocket

import torch
from ultralytics import YOLO
import uvicorn

app = FastAPI(title="YOLOE Detection Service", version="0.1.0")

# --------- Schemas ---------
class Box(BaseModel):
    x1: float; y1: float; x2: float; y2: float

class Detection(BaseModel):
    class_id: int = Field(..., description="Index of the predicted class")
    class_name: str
    confidence: float
    box: Box

class PredictionResponse(BaseModel):
    detections: List[Detection]
    num_detections: int
    model: Dict[str, str]
    image: Dict[str, int]

class ModelInfo(BaseModel):
    name: str
    classes: dict
    device: str
    conf_threshold: float
    iou_threshold: float

# --------- Detector ---------
class YOLOEDetector:
    def __init__(self):
        self.model_path = os.environ.get("YOLOE_MODEL", "yoloe-backend/yolov8n.pt")
        self.conf_threshold = float(os.environ.get("YOLOE_CONF", 0.25))
        self.iou_threshold = float(os.environ.get("YOLOE_IOU", 0.45))
        self.device = os.environ.get("YOLOE_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")

        self.model = YOLO(self.model_path)
        self.model.fuse()
        self.model.to(self.device)
        self.name = os.path.basename(self.model_path)
        self.classes = getattr(self.model, "names", {})

    def predict_pil(self, image: Image.Image):
        results = self.model(
            image,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False,
        )
        r = results[0]
        detections = []
        if r.boxes is not None and len(r.boxes) > 0:
            xyxy = r.boxes.xyxy.tolist()
            conf = r.boxes.conf.tolist()
            cls = r.boxes.cls.tolist()
            for (x1, y1, x2, y2), c, k in zip(xyxy, conf, cls):
                detections.append({
                    "class_id": int(k),
                    "class_name": self.classes.get(int(k), str(int(k))),
                    "confidence": float(c),
                    "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                })
        return {
            "detections": detections,
            "num_detections": len(detections),
            "model": {"name": self.name, "device": self.device},
            "image": {"width": image.width, "height": image.height},
        }

_detector = None
def get_detector():
    global _detector
    if _detector is None:
        _detector = YOLOEDetector()
    return _detector

# --------- Routes ---------
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/model", response_model=ModelInfo)
def model_info():
    d = get_detector()
    return ModelInfo(
        name=d.name, classes=d.classes, device=d.device,
        conf_threshold=d.conf_threshold, iou_threshold=d.iou_threshold
    )

@app.post("/predict", response_model=PredictionResponse)
async def predict(file: UploadFile = File(...)):
    try:
        image = Image.open(io.BytesIO(await file.read())).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")
    return get_detector().predict_pil(image)

class Base64Image(BaseModel):
    image_b64: str  # may include data URL prefix

@app.post("/predict-b64", response_model=PredictionResponse)
async def predict_b64(payload: Base64Image):
    b64 = payload.image_b64.split(",", 1)[-1]
    try:
        image = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image: {e}")
    return get_detector().predict_pil(image)

telemetry_manager = setup_websocket(app, get_detector)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)