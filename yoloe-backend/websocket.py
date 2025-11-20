"""
WebSocket server for real-time telemetry with YOLO object detection.
Receives image frames and telemetry from JetBot, runs inference, and broadcasts
annotated images with detections to frontend clients.

Runs on port 8002 to avoid conflicts with jetbot-backend API (port 8000) and SSH tunnels.
"""

import asyncio
import base64
import io
import json
import time
from typing import Any, Dict, Optional

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from PIL import Image


class TelemetryManager:
    """
    Manages WebSocket connections and broadcasts telemetry with YOLO detections.
    Distinguishes between JetBot (JSON only) and frontend (JSON + images) clients.
    """

    def __init__(self):
        """Initialize telemetry manager."""
        self.active_connections: Dict[WebSocket, str] = {}  # websocket -> client_type ("jetbot" or "frontend")
        self._latest_telemetry: Optional[Dict[str, Any]] = None
        self._telemetry_lock = asyncio.Lock()
        self._broadcast_task: Optional[asyncio.Task] = None
        self._broadcast_running = False

    async def connect_websocket(self, websocket: WebSocket, client_type: str = "frontend"):
        """
        Handle new WebSocket connection.

        Args:
            websocket: WebSocket connection
            client_type: "jetbot" (JSON only) or "frontend" (JSON + images)
        """
        await websocket.accept()
        self.active_connections[websocket] = client_type
        print(f"WebSocket client connected ({client_type}). Total clients: {len(self.active_connections)}")

        # Start broadcast task if not already running
        if not self._broadcast_running:
            self._broadcast_running = True
            self._broadcast_task = asyncio.create_task(self._broadcast_telemetry())

        # Send latest telemetry immediately if available
        async with self._telemetry_lock:
            if self._latest_telemetry:
                try:
                    # Send appropriate data based on client type
                    message = self._format_message_for_client(self._latest_telemetry, client_type)

                    # For frontend clients, only send if we have image data
                    if client_type == "frontend" and "image" not in message:
                        print(f"[WebSocket] Frontend client connected, waiting for first frame...")
                    else:
                        await websocket.send_text(json.dumps(message))
                except Exception as e:
                    print(f"Error sending initial telemetry: {e}")

        try:
            # Keep connection alive and handle messages
            while True:
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)

                    # Handle ping/pong
                    if data == "ping":
                        await websocket.send_text("pong")
                        continue

                    # Parse JSON message
                    try:
                        message = json.loads(data)
                        await self._handle_message(websocket, client_type, message)
                    except json.JSONDecodeError:
                        # Not JSON, might be plain text
                        if data != "ping":
                            print(f"Received non-JSON message: {data[:100]}")

                except asyncio.TimeoutError:
                    # Timeout is fine, just continue
                    continue
        except WebSocketDisconnect:
            # Remove connection
            if websocket in self.active_connections:
                del self.active_connections[websocket]
            print(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

            # Stop broadcast task if no clients connected
            if len(self.active_connections) == 0 and self._broadcast_task:
                self._broadcast_running = False
                self._broadcast_task.cancel()
                try:
                    await self._broadcast_task
                except asyncio.CancelledError:
                    pass
                self._broadcast_task = None

    async def _handle_message(self, websocket: WebSocket, client_type: str, message: Dict[str, Any]):
        """
        Handle incoming WebSocket messages based on message type.

        Args:
            websocket: WebSocket connection
            client_type: "jetbot" or "frontend"
            message: Parsed JSON message
        """
        msg_type = message.get("type")

        if client_type == "jetbot":
            # JetBot can send frames or label management requests
            if msg_type == "frame":
                # Process frame from JetBot
                image_b64 = message.get("image")
                if image_b64:
                    telemetry = {"ultrasonic": message.get("ultrasonic", {}), "motors": message.get("motors", {})}
                    detection_result = await self.process_jetbot_frame(image_b64, telemetry)
                    # Send detection results back to JetBot (JSON only)
                    from main import get_detector

                    response = {"type": "detections", "detections": detection_result.get("detections", []), "num_detections": detection_result.get("num_detections", 0), "model": detection_result.get("model", {}), "labels": get_detector().get_labels()}
                    # Include error if present
                    if "error" in detection_result:
                        response["error"] = detection_result["error"]
                    await websocket.send_text(json.dumps(response))

            elif msg_type == "set_labels":
                # Handle label update from JetBot
                from main import get_detector

                labels = message.get("labels", [])
                detector = get_detector()
                result = detector.set_labels(labels)
                if result["success"]:
                    await self.broadcast_event("labels_updated", {"labels": detector.get_labels()})
                # Send response back
                await websocket.send_text(json.dumps({"type": "labels_response", "success": result["success"], "labels": result.get("labels", []), "message": result.get("message", "")}))

        elif client_type == "frontend":
            # Frontend can request label management
            if msg_type == "set_labels":
                from main import get_detector

                labels = message.get("labels", [])
                detector = get_detector()
                result = detector.set_labels(labels)
                if result["success"]:
                    await self.broadcast_event("labels_updated", {"labels": detector.get_labels()})
                await websocket.send_text(json.dumps({"type": "labels_response", "success": result["success"], "labels": result.get("labels", []), "message": result.get("message", "")}))

    def _format_message_for_client(self, telemetry: Dict[str, Any], client_type: str) -> Dict[str, Any]:
        """
        Format telemetry message based on client type.

        Args:
            telemetry: Full telemetry data
            client_type: "jetbot" or "frontend"

        Returns:
            Formatted message dict
        """
        if client_type == "jetbot":
            # JetBot gets JSON only (no images)
            return {
                "timestamp": telemetry.get("timestamp"),
                "ultrasonic": telemetry.get("ultrasonic", {}),
                "motors": telemetry.get("motors", {}),
                "detections": telemetry.get("detections", []),
                "num_detections": telemetry.get("num_detections", 0),
                "model": telemetry.get("model", {}),
                "labels": telemetry.get("labels", []),
            }
        else:
            # Frontend gets full telemetry with images
            return telemetry

    async def process_jetbot_frame(self, image_b64: str, telemetry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process image frame from JetBot: run YOLO inference, draw boxes, and update telemetry.

        Args:
            image_b64: Base64 encoded image from JetBot
            telemetry: Telemetry data from JetBot (ultrasonic, motors, etc.)

        Returns:
            dict: Detection results (JSON format for JetBot)
        """
        try:
            # Decode base64 image
            b64_data = image_b64.split(",", 1)[-1] if "," in image_b64 else image_b64
            image_bytes = base64.b64decode(b64_data)
            pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # Run YOLO inference
            from main import get_detector

            detector = get_detector()
            detection_result = detector.predict_pil(pil_image)

            # Convert PIL to numpy array for OpenCV
            image_np = np.array(pil_image)
            # Convert RGB to BGR for OpenCV
            image_bgr = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)

            # Draw bounding boxes on image
            annotated_image = self._draw_detections(image_bgr, detection_result["detections"])

            # Encode annotated image as JPEG
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]  # 85% quality
            _, encoded_image = cv2.imencode(".jpg", annotated_image, encode_param)
            annotated_image_b64 = base64.b64encode(encoded_image).decode("utf-8")

            # Construct combined telemetry message
            combined_telemetry = {
                "timestamp": time.time(),
                "ultrasonic": telemetry.get("ultrasonic", {}),
                "motors": telemetry.get("motors", {}),
                "detections": detection_result["detections"],
                "num_detections": detection_result["num_detections"],
                "model": detection_result["model"],
                "labels": detector.get_labels(),  # Include current labels
                "image": annotated_image_b64,  # Annotated image with bounding boxes
                "raw_image": image_b64,  # Keep raw image for reference
            }

            # Update latest telemetry
            async with self._telemetry_lock:
                self._latest_telemetry = combined_telemetry

            # Return detection results (JSON format for JetBot)
            return detection_result

        except Exception as e:
            print(f"Error processing JetBot frame: {e}")
            # Return error response instead of raising HTTPException (WebSocket can't use HTTPException)
            return {"detections": [], "num_detections": 0, "model": {"name": "error", "device": "unknown"}, "error": f"Failed to process frame: {str(e)}"}

    def _draw_detections(self, image: np.ndarray, detections: list) -> np.ndarray:
        """
        Draw bounding boxes and labels on image.

        Args:
            image: BGR image as numpy array
            detections: List of detection dictionaries with box, class_name, confidence

        Returns:
            Annotated image
        """
        annotated = image.copy()

        for det in detections:
            box = det["box"]
            x1, y1, x2, y2 = int(box["x1"]), int(box["y1"]), int(box["x2"]), int(box["y2"])
            class_name = det["class_name"]
            confidence = det["confidence"]

            # Draw bounding box
            color = (0, 255, 0)  # Green in BGR
            thickness = 2
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)

            # Draw label with confidence
            label = f"{class_name} {confidence:.2f}"
            label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            label_y = max(y1, label_size[1] + 10)

            # Draw label background
            cv2.rectangle(annotated, (x1, label_y - label_size[1] - 10), (x1 + label_size[0], label_y), color, -1)

            # Draw label text
            cv2.putText(annotated, label, (x1, label_y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        return annotated

    async def _broadcast_telemetry(self):
        """
        Background task that broadcasts latest telemetry to all connected frontend clients.
        """
        try:
            while self._broadcast_running:
                if len(self.active_connections) == 0:
                    await asyncio.sleep(0.1)
                    continue

                # Get latest telemetry
                async with self._telemetry_lock:
                    telemetry_data = self._latest_telemetry

                # Broadcast to all connected clients with appropriate format
                if telemetry_data:
                    disconnected_clients = set()

                    for client, client_type in list(self.active_connections.items()):
                        try:
                            # Format message based on client type
                            message = self._format_message_for_client(telemetry_data, client_type)

                            # For frontend clients, skip if no image data yet
                            if client_type == "frontend" and "image" not in message:
                                continue

                            await client.send_text(json.dumps(message))
                        except Exception as e:
                            # Client disconnected or error
                            print(f"Error sending to client ({client_type}): {e}")
                            disconnected_clients.add(client)

                    # Remove disconnected clients
                    for client in disconnected_clients:
                        if client in self.active_connections:
                            del self.active_connections[client]

                # Small delay to prevent overwhelming the system (~30 FPS)
                await asyncio.sleep(0.033)

        except asyncio.CancelledError:
            print("Broadcast task cancelled")
        except Exception as e:
            print(f"Error in broadcast task: {e}")
        finally:
            self._broadcast_running = False

    async def broadcast_event(self, event_type: str, event_data: Dict[str, Any]):
        """
        Broadcast an event message to all connected WebSocket clients.

        Args:
            event_type: Type of event (e.g., "labels_updated", "model_changed")
            event_data: Event-specific data
        """
        if len(self.active_connections) == 0:
            return

        message = {"type": "event", "event_type": event_type, "timestamp": time.time(), "data": event_data}

        message_json = json.dumps(message)
        disconnected_clients = set()

        for client in list(self.active_connections.keys()):
            try:
                await client.send_text(message_json)
            except Exception as e:
                print(f"Error sending event to client: {e}")
                disconnected_clients.add(client)

        # Remove disconnected clients
        for client in disconnected_clients:
            if client in self.active_connections:
                del self.active_connections[client]


# Global telemetry manager instance
_telemetry_manager: Optional[TelemetryManager] = None


def setup_websocket(app: FastAPI) -> TelemetryManager:
    """
    Setup WebSocket routes and return telemetry manager.

    Args:
        app: FastAPI application instance

    Returns:
        TelemetryManager instance
    """
    global _telemetry_manager
    _telemetry_manager = TelemetryManager()

    @app.websocket("/ws/telemetry")
    async def websocket_telemetry(websocket: WebSocket, client: str = Query("frontend", description="Client type: 'jetbot' (JSON only) or 'frontend' (JSON + images)")):
        """
        WebSocket endpoint for real-time telemetry with YOLO detections.

        Query parameters:
        - client: "jetbot" (JSON only) or "frontend" (JSON + images). Default: "frontend"

        For JetBot clients (client=jetbot), messages include:
        {
            "timestamp": 1234567890.123,
            "ultrasonic": {...},
            "motors": {...},
            "detections": [...],
            "num_detections": 1,
            "model": {...},
            "labels": ["person", "bicycle", ...]
        }

        For Frontend clients (client=frontend), messages include everything above PLUS:
        {
            "image": "base64_encoded_jpeg_string_with_boxes",
            "raw_image": "base64_encoded_jpeg_string_original"
        }

        Event messages (when labels are updated):
        {
            "type": "event",
            "event_type": "labels_updated",
            "timestamp": 1234567890.123,
            "data": {
                "labels": ["person", "bicycle", ...]
            }
        }
        """
        await _telemetry_manager.connect_websocket(websocket, client_type=client)

    return _telemetry_manager
