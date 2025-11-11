from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict
from PIL import Image
import base64, io, os
from websocket import setup_websocket

import torch
try:
    from ultralytics import YOLOE
    print("YOLO-E imported successfully")
except ImportError as e:
    print(f"YOLO-E import failed: {e}")
    raise
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
        self.model_path = "yoloe-backend/yoloe-l.pt"
        self.conf_threshold = 0.25
        self.iou_threshold = 0.45
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Initialize model
        self.model = None
        self.current_prompts: List[str] = []
        self.init_model()
    
    def init_model(self):
        """Initialize YOLO-E model with device selection and error handling."""
        try:
            print(f"Using device: {self.device}")
            print(f"Loading YOLO-E model: {self.model_path}")
            
            # Try to load model, fallback to CPU if CUDA fails
            try:
                self.model = YOLOE(self.model_path).to(self.device)
            except RuntimeError as cuda_error:
                if "CUDA" in str(cuda_error) and self.device == "cuda":
                    print(f"CUDA error encountered: {cuda_error}")
                    print("Falling back to CPU mode...")
                    self.device = "cpu"
                    self.model = YOLOE(self.model_path).to(self.device)
                else:
                    raise
            
            print("YOLO-E model loaded successfully!")
            self.name = os.path.basename(self.model_path)
        except Exception as e:
            print(f"Failed to load YOLO-E model: {e}")
            self.model = None
            raise
    
    def set_labels(self, labels: List[str]) -> Dict:
        """
        Set open-vocabulary prompts for YOLO-E detection.
        
        YOLO-E supports true open-vocabulary detection - you can detect any objects
        described by the prompt strings, not just fixed COCO classes.
        
        Args:
            labels: List of prompt strings for open-vocabulary detection.
                    These are the actual classes the model will detect.
                    Example: ["person", "bicycle", "red car", "dog running"]
        
        Returns:
            dict: Success status and current prompts
        """
        try:
            if self.model is None:
                return {"success": False, "labels": [], "message": "YOLO-E model not loaded"}
            
            # Set classes with the text embeddings (YOLO-E open-vocabulary)
            text_embeddings = self.model.get_text_pe(labels)
            self.model.set_classes(labels, text_embeddings)
            self.current_prompts = labels.copy()
            
            print(f"Set YOLO-E prompts to: {labels}")
            return {
                "success": True,
                "labels": self.current_prompts.copy(),
                "message": f"Prompts set to: {labels}"
            }
        except Exception as e:
            print(f"Failed to set prompts: {e}")
            return {"success": False, "labels": self.current_prompts.copy(), "message": f"Failed to set prompts: {str(e)}"}
    
    def get_labels(self) -> List[str]:
        """
        Get current prompts (labels) for YOLO-E detection.
        
        Returns:
            List[str]: List of current prompt strings
        """
        return self.current_prompts.copy()
    
    def _get_class_name(self, class_id: int) -> str:
        """
        Get class name for a given class ID.
        
        In YOLO-E, class_id indexes into current_prompts array, not COCO classes.
        """
        if 0 <= class_id < len(self.current_prompts):
            return self.current_prompts[class_id]
        return f"id{class_id}"

    def predict_pil(self, image: Image.Image):
        """
        Run YOLO-E detection on image with current prompts.
        
        If no prompts are set, uses default ["person"] prompt.
        """
        if self.model is None:
            return {
                "detections": [],
                "num_detections": 0,
                "model": {"name": self.name if hasattr(self, 'name') else "unknown", "device": self.device},
                "image": {"width": image.width, "height": image.height},
            }
        
        # Set default prompts if none set
        if not self.current_prompts:
            default_prompts = ["person"]
            text_embeddings = self.model.get_text_pe(default_prompts)
            self.model.set_classes(default_prompts, text_embeddings)
            self.current_prompts = default_prompts.copy()
        
        # Run YOLO-E inference
        results = self.model.predict(
            image,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False,
        )
        
        r = results[0]
        detections = []
        
        if r.boxes is not None and len(r.boxes) > 0:
            try:
                # Extract detection data
                cls_indices = r.boxes.cls.int().cpu().tolist()
                confidences = r.boxes.conf.float().cpu().tolist()
                xyxy_boxes = r.boxes.xyxy.int().cpu().tolist()
            except Exception:
                # Fallback for older tensor API
                cls_indices = []
                confidences = []
                xyxy_boxes = []
                for b in r.boxes:
                    cls_indices.append(int(b.cls))
                    confidences.append(float(b.conf))
                    xyxy_boxes.append(b.xyxy.int().cpu().numpy().flatten().tolist())
            
            # YOLO-E: class_id indexes current_prompts, not COCO classes
            for (x1, y1, x2, y2), c, k in zip(xyxy_boxes, confidences, cls_indices):
                class_id = int(k)
                detections.append({
                    "class_id": class_id,
                    "class_name": self._get_class_name(class_id),
                    "confidence": float(c),
                    "box": {"x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2)},
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
    # For YOLO-E, classes are the current prompts
    classes_dict = {i: prompt for i, prompt in enumerate(d.current_prompts)} if d.current_prompts else {}
    return ModelInfo(
        name=d.name, classes=classes_dict,
        device=d.device, conf_threshold=d.conf_threshold, iou_threshold=d.iou_threshold
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

telemetry_manager = setup_websocket(app)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)