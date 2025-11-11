"""
Websocket for YOLOE
"""
import json
import base64, io

import cv2
import numpy as np
from PIL import Image
from typing import Set
from fastapi import WebSocket, WebSocketDisconnect, status

def setup_websocket(app, get_detector):

    @app.websocket("/ws/yoloe")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()

        # Connection label list
        active_labels: Set[str] = set()
        
        try:
            await ws.send_text(json.dumps({"type": "hello", "message": "YOLOE WebSocket ready"}))

            while True:
                raw = await ws.receive_text()

                # Parse json
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "request_id": None,
                        "message": "Invalid JSON"
                    }))  
                    continue

                mtype = msg.get("type")
                req_id = msg.get("request_id")

                # Handle words
                if mtype == "words":
                    labels = msg.get("labels")

                    if not isinstance(labels, list):
                        await ws.send_text(json.dumps({
                            "type": "error",
                            "request_id": req_id,
                            "message": "'labels' must be a list of strings"
                        }))  
                        continue

                    # Normalize strings
                    active_labels = {str(x).strip() for x in labels if str(x).strip()}

                    # Send acknowledgement 
                    await ws.send_text(json.dumps({
                        "type": "words_ack",
                        "request_id": req_id,
                        "status": "ok",
                        "active_labels": sorted(list(active_labels))
                    }))
                    continue

                # Handle images
                elif mtype == "image":
                    b64 = msg.get("image_b64")
                    if not isinstance(b64, str) or not b64:
                        await ws.send_text(json.dumps({
                            "type": "error", 
                            "request_id": req_id,
                            "message": "'image_b64' missing or not a string"
                        }))
                        continue

                    # Convert b64 to PIL
                    try:
                        pil_img = _pil_from_b64(b64)
                    except Exception as e:
                        await ws.send_text(json.dumps({
                            "type": "error", 
                            "request_id": req_id,
                            "message": f"Invalid image: {e}"
                        }))
                        continue

                    # Run yoloe
                    d = get_detector()
                    result = d.predict_pil(pil_img)
                    detections = result.get("detections", [])

                    # Sort through labels
                    if active_labels:
                        detections = [det for det in detections if det["class_name"] in active_labels]

                    # Draw
                    cv_img = _cv2_draw(pil_img, detections)

                    # Encode and send
                    final_b64 = _encode_jpeg_b64(cv_img, quality = 75)
                    payload = {
                        "type": "inference_result",
                        "request_id": req_id,
                        "detections": detections,
                        "num_detections": len(detections),
                        "model": result.get("model", {}),
                        "image": result.get("image", {}),
                        "annotated_image_b64": final_b64
                    }
                    await ws.send_text(json.dumps(payload))
                    continue

                else:
                    await ws.send_text(json.dumps({
                        "type": "error",
                        "request_id": req_id,
                        "message": f"Unknown type '{mtype}'"
                    }))

        except WebSocketDisconnect:
            return
        except Exception:
            # Close to any exception
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)

# ---------- Helpers ----------

# Decodes data URL or raw base64 string into bytes.
def _decode_data_url(b64: str) -> bytes:
    if "," in b64:
        # Remove metadata prefix
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)

# Convert base64 (jpg/png) to PIL RGB image
def _pil_from_b64(b64: str) -> Image.Image:
    raw = _decode_data_url(b64)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return img

# Draw bounding boxes from the detections on the image
def _cv2_draw(pil_img: Image.Image, detections, max_width: int = 640):
    cv_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    
    # Ensure shape and scale
    h, w = cv_img.shape[:2]
    scale = 1.0
    if w > max_width:
        scale = max_width / float(w)
        cv_img = cv2.resize(cv_img, (int(w * scale), int(h * scale)))

    # Draw each detection
    for det in detections:
        box = det["box"]
        x1, y1, x2, y2 = box["x1"], box["y1"], box["x2"], box["y2"]
        if scale != 1.0:
            x1, y1, x2, y2 = x1 * scale, y1 * scale, x2 * scale, y2 * scale

        # Box
        p1, p2 = (int(x1), int(y1)), (int(x2), int(y2))
        cv2.rectangle(cv_img, p1, p2, (0, 255, 0), 2)
        # Text
        label = f'{det["class_name"]} {det["confidence"]:.2f}'
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(cv_img, (p1[0], p1[1] - th - 4), 
                      (p1[0] + tw + 4, p1[1]), (0, 255, 0), -1)
        cv2.putText(cv_img, label, (p1[0] + 2, p1[1] - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        
    return cv_img

# Encode cv2 image to base64 with metadata
def _encode_jpeg_b64(cv_img: np.ndarray, quality: int = 75) -> str:
    ok, buf = cv2.imencode(".jpg", cv_img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])

    if not ok:
        raise RuntimeError("JPEG encode failed")
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
