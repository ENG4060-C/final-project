"""
Main entry point for the ADK-based robot control system.
Connects to telemetry stream and runs the Director → Observer/Pilot loop.
"""

import asyncio
import json
import os
import threading
import time
from typing import Dict

import websockets
from dotenv import load_dotenv
from google.adk import Runner
from root_agent import root_agent

# Load environment
load_dotenv()

# Configuration
WEBSOCKET_URL = "ws://localhost:8002/ws/telemetry?client=frontend"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Check for required environment
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in environment. Please add it to .env file.")

# Global telemetry state
latest_telemetry: Dict = {}
telemetry_lock = threading.Lock()


class TelemetryStream(threading.Thread):
    """Background thread to maintain the latest telemetry from the robot."""

    def __init__(self):
        super().__init__()
        self.daemon = True
        self.running = True
        self.connected = False

    def run(self):
        asyncio.run(self._listen())

    async def _listen(self):
        while self.running:
            try:
                async with websockets.connect(WEBSOCKET_URL) as ws:
                    self.connected = True
                    print("[Telemetry] Connected to sensor stream (port 8002).")
                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)

                        # Update global telemetry
                        with telemetry_lock:
                            global latest_telemetry
                            latest_telemetry = {"ultrasonic": data.get("ultrasonic", {}), "detections": data.get("detections", []), "num_detections": data.get("num_detections", 0), "labels": data.get("labels", []), "timestamp": data.get("timestamp", 0)}

            except Exception as e:
                self.connected = False
                print(f"[Telemetry] Stream disconnected: {e}. Reconnecting in 2s...")
                await asyncio.sleep(2)


def get_latest_telemetry() -> Dict:
    """Get the latest telemetry data thread-safely."""
    with telemetry_lock:
        return latest_telemetry.copy()


def format_telemetry_context() -> str:
    """Format telemetry data as context string for agents."""
    telemetry = get_latest_telemetry()

    if not telemetry:
        return "[TELEMETRY] No data available yet."

    ultrasonic = telemetry.get("ultrasonic", {})
    distance_m = ultrasonic.get("distance_m", "N/A")
    distance_cm = ultrasonic.get("distance_cm", "N/A")

    detections = telemetry.get("detections", [])
    num_detections = telemetry.get("num_detections", 0)
    labels = telemetry.get("labels", [])

    context = f"""
[REAL-TIME TELEMETRY]
Ultrasonic Distance: {distance_m}m ({distance_cm}cm)
Active Labels: {", ".join(labels) if labels else "None"}
Current Detections: {num_detections} objects
"""

    if detections:
        context += "Detected Objects:\n"
        for i, det in enumerate(detections[:5], 1):  # Show max 5
            box = det.get("box", {})
            context += f"  {i}. {det.get('class_name', 'unknown')} (conf: {det.get('confidence', 0):.2f}) at [{box.get('x1', 0):.0f}, {box.get('y1', 0):.0f}, {box.get('x2', 0):.0f}, {box.get('y2', 0):.0f}]\n"

    return context


def main():
    print("=" * 60)
    print("  ADK Robot Control System")
    print("  Architecture: Director → Observer/Pilot Loop")
    print("=" * 60)

    # Start telemetry stream
    telemetry_stream = TelemetryStream()
    telemetry_stream.start()
    print("\nWaiting for telemetry connection...")
    while not telemetry_stream.connected:
        time.sleep(0.5)
    print("✓ Telemetry active")

    # Wait for initial data
    print("Waiting for initial sensor data...")
    while not get_latest_telemetry():
        time.sleep(0.5)
    print("✓ Sensors online\n")

    # Run the agent system
    try:
        runner = Runner(agent=root_agent, api_key=GOOGLE_API_KEY)

        # Main interaction loop
        while True:
            # Inject telemetry into shared state for all agents
            telemetry = get_latest_telemetry()
            runner.state["telemetry:ultrasonic_distance_m"] = telemetry.get("ultrasonic", {}).get("distance_m", "N/A")
            runner.state["telemetry:ultrasonic_distance_cm"] = telemetry.get("ultrasonic", {}).get("distance_cm", "N/A")
            runner.state["telemetry:num_detections"] = telemetry.get("num_detections", 0)
            runner.state["telemetry:active_labels"] = ", ".join(telemetry.get("labels", []))

            # Format detected objects for state
            detections = telemetry.get("detections", [])
            if detections:
                detection_summary = []
                for det in detections[:3]:  # Top 3
                    box = det.get("box", {})
                    detection_summary.append(f"{det.get('class_name', 'unknown')} at [{box.get('x1', 0):.0f},{box.get('y1', 0):.0f},{box.get('x2', 0):.0f},{box.get('y2', 0):.0f}]")
                runner.state["telemetry:detected_objects"] = "; ".join(detection_summary)
            else:
                runner.state["telemetry:detected_objects"] = "None"

            # Get telemetry context for display
            telemetry_context = format_telemetry_context()

            # Get user input
            user_input = input("\n[USER] Your command: ")
            if user_input.lower() in ["exit", "quit", "q"]:
                break

            # Show telemetry to user
            print(telemetry_context)

            # Run the agent (telemetry is now in state, accessible via {telemetry:...})
            print("\n[SYSTEM] Director analyzing request...")
            result = runner.run(user_input)

            # Display result
            print(f"\n[RESULT] {result}")

            # Check if mission is complete by looking at result
            if "mission_status" in str(result) and "complete" in str(result):
                print("\n✓ Mission completed! Ready for next task.")
                continue

    except KeyboardInterrupt:
        print("\n\n[SYSTEM] Interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Cleanup
        telemetry_stream.running = False
        print("\n[SYSTEM] Shutting down...")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
