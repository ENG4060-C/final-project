"""
Test script for yoloe-backend WebSocket server.
Connects as a frontend client and displays annotated images with telemetry data.
Alternates between label sets every 3 seconds to demonstrate label switching.
"""

import asyncio
import base64
import json
import time
from datetime import datetime
from io import BytesIO

import cv2
import numpy as np
import websockets
from PIL import Image

WEBSOCKET_URL = "ws://localhost:8002/ws/telemetry?client=frontend"
LABEL_SETS = [["person"], ["laptop", "chair"]]
LABEL_SWITCH_INTERVAL = 3.0  # seconds


class WebSocketTester:
    def __init__(self):
        self.current_label_set_index = 0
        self.last_label_switch_time = time.time()
        self.frame_count = 0
        self.detection_count = 0

    async def connect_and_test(self):
        """Connect to WebSocket and test functionality."""
        print("=" * 60)
        print("YOLO-E WebSocket Test Client")
        print("=" * 60)
        print(f"Connecting to: {WEBSOCKET_URL}")
        print(f"Label sets: {LABEL_SETS}")
        print(f"Switching labels every {LABEL_SWITCH_INTERVAL} seconds")
        print("Press 'q' to quit")
        print("=" * 60)

        try:
            async with websockets.connect(WEBSOCKET_URL) as websocket:
                print("Connected successfully!")

                # Start label switching task
                label_task = asyncio.create_task(self.switch_labels_periodically(websocket))

                try:
                    async for message in websocket:
                        await self.handle_message(websocket, message)
                finally:
                    label_task.cancel()
                    try:
                        await label_task
                    except asyncio.CancelledError:
                        pass

        except websockets.exceptions.ConnectionClosed:
            print("\nConnection closed")
        except Exception as e:
            print(f"\nError: {e}")
            raise

    async def switch_labels_periodically(self, websocket):
        """Periodically switch between label sets."""
        while True:
            try:
                await asyncio.sleep(LABEL_SWITCH_INTERVAL)

                # Switch to next label set
                self.current_label_set_index = (self.current_label_set_index + 1) % len(LABEL_SETS)
                new_labels = LABEL_SETS[self.current_label_set_index]

                print(f"\n[LABEL SWITCH] Setting labels to: {new_labels}")

                # Send set_labels message
                message = {"type": "set_labels", "labels": new_labels}
                await websocket.send(json.dumps(message))
                self.last_label_switch_time = time.time()

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in label switching: {e}")

    async def handle_message(self, websocket, message_text):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message_text)

            # Handle event messages
            if data.get("type") == "event":
                if data.get("event_type") == "labels_updated":
                    labels = data.get("data", {}).get("labels", [])
                    print(f"[EVENT] Labels updated: {labels}")
                return

            # Handle labels_response
            if data.get("type") == "labels_response":
                labels = data.get("labels", [])
                success = data.get("success", True)
                print(f"[RESPONSE] Labels set: {labels} (success: {success})")
                return

            # Handle telemetry messages (with images)
            if "image" in data:
                self.frame_count += 1
                self.detection_count += data.get("num_detections", 0)

                # Decode and display image
                await self.display_frame(data)

        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {e}")
        except Exception as e:
            print(f"Error handling message: {e}")

    async def display_frame(self, data):
        """Display frame with annotations and telemetry overlay."""
        try:
            # Decode base64 image
            image_b64 = data.get("image", "")
            if not image_b64:
                return

            # Remove data URL prefix if present
            b64_data = image_b64.split(",", 1)[-1] if "," in image_b64 else image_b64
            image_bytes = base64.b64decode(b64_data)

            # Convert to numpy array
            nparr = np.frombuffer(image_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                print("Failed to decode image")
                return

            # Get telemetry data
            ultrasonic = data.get("ultrasonic", {})
            motors = data.get("motors", {})
            detections = data.get("detections", [])
            labels = data.get("labels", [])
            timestamp = data.get("timestamp", time.time())

            # Draw telemetry overlay
            self.draw_telemetry_overlay(frame, ultrasonic, motors, detections, labels, timestamp)

            # Display frame
            cv2.imshow("YOLO-E WebSocket Test", frame)

            # Handle key press
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                print("\nQuitting...")
                cv2.destroyAllWindows()
                raise KeyboardInterrupt

        except Exception as e:
            print(f"Error displaying frame: {e}")

    def draw_telemetry_overlay(self, frame, ultrasonic, motors, detections, labels, timestamp):
        """Draw telemetry information overlay on frame."""
        # Font settings
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        thickness = 2
        color = (0, 255, 0)  # Green
        bg_color = (0, 0, 0)  # Black background

        # Calculate overlay position
        y_offset = 20
        line_height = 25

        # Prepare text lines
        lines = []

        # Timestamp
        dt = datetime.fromtimestamp(timestamp)
        lines.append(f"Time: {dt.strftime('%H:%M:%S.%f')[:-3]}")

        # Ultrasonic sensor
        dist_m = ultrasonic.get("distance_m")
        dist_cm = ultrasonic.get("distance_cm")
        if dist_m is not None:
            lines.append(f"Ultrasonic: {dist_m:.3f}m ({dist_cm:.1f}cm)")
        else:
            lines.append("Ultrasonic: N/A")

        # Motor values
        left_motor = motors.get("left")
        right_motor = motors.get("right")
        if left_motor is not None and right_motor is not None:
            lines.append(f"Motors: L={left_motor:.2f} R={right_motor:.2f}")
        else:
            lines.append("Motors: N/A")

        # Detections
        num_detections = len(detections)
        lines.append(f"Detections: {num_detections}")

        # Current labels
        labels_str = ", ".join(labels) if labels else "None"
        lines.append(f"Labels: [{labels_str}]")

        # Stats
        lines.append(f"Frames: {self.frame_count} | Total detections: {self.detection_count}")

        # Time until next label switch
        time_until_switch = LABEL_SWITCH_INTERVAL - (time.time() - self.last_label_switch_time)
        if time_until_switch > 0:
            lines.append(f"Next label switch in: {time_until_switch:.1f}s")

        # Draw text with background
        for i, line in enumerate(lines):
            y_pos = y_offset + (i * line_height)

            # Get text size for background
            (text_width, text_height), baseline = cv2.getTextSize(line, font, font_scale, thickness)

            # Draw background rectangle
            cv2.rectangle(frame, (10, y_pos - text_height - 5), (10 + text_width + 10, y_pos + 5), bg_color, -1)

            # Draw text
            cv2.putText(frame, line, (15, y_pos), font, font_scale, color, thickness)

        # Draw detection list (if any)
        if detections:
            y_start = y_offset + (len(lines) * line_height) + 20
            for i, det in enumerate(detections[:5]):  # Show max 5 detections
                class_name = det.get("class_name", "unknown")
                confidence = det.get("confidence", 0.0)
                det_text = f"{i + 1}. {class_name}: {confidence:.2f}"

                y_pos = y_start + (i * line_height)

                # Get text size
                (text_width, text_height), baseline = cv2.getTextSize(det_text, font, font_scale, thickness)

                # Draw background
                cv2.rectangle(frame, (10, y_pos - text_height - 5), (10 + text_width + 10, y_pos + 5), bg_color, -1)

                # Draw text
                cv2.putText(frame, det_text, (15, y_pos), font, font_scale, color, thickness)


async def main():
    """Main entry point."""
    tester = WebSocketTester()

    try:
        await tester.connect_and_test()
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    finally:
        cv2.destroyAllWindows()
        print("Test completed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        cv2.destroyAllWindows()
