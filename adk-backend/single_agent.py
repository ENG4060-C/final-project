"""
Single-Agent Gemini Voice Loop (Director + Observer + Pilot combined).

This agent:
1. Listens to the JetBot telemetry stream (via YOLO-E WebSocket) for sensor data.
2. Uses voice/text with Gemini to reason about the task.
3. Uses vision tools (not video streaming) to see the environment when needed.
4. Uses movement tools to control the robot.

No video is sent to Gemini to minimize API costs.
"""

import asyncio
import json
import os
import threading
import time
from typing import Dict

import websockets
from dotenv import load_dotenv

# Google GenAI SDK
from google import genai
from google.genai import types

# Import tools
from shared_tools import move_arc_tool, move_distance_tool, rotate_robot_tool, rotate_until_centered_tool, scan_surroundings_tool, set_vision_labels_tool, stop_robot_tool, get_bounding_box_percentage_tool

# Load environment variables
load_dotenv()

# Configuration
API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_ID = "gemini-2.0-flash-exp"  # Fast, multimodal model
WEBSOCKET_URL = "ws://localhost:8002/ws/telemetry?client=frontend"

# Global state for telemetry (ultrasonic, detections, etc.)
latest_telemetry: Dict = {}
telemetry_lock = threading.Lock()


class TelemetryStream(threading.Thread):
    """Background thread to maintain the latest telemetry data."""

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
                    print("[Telemetry] Connected to sensor stream.")
                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)

                        # Update global telemetry (ultrasonic, detections, motors)
                        with telemetry_lock:
                            global latest_telemetry
                            latest_telemetry = {"ultrasonic": data.get("ultrasonic", {}), "detections": data.get("detections", []), "num_detections": data.get("num_detections", 0), "labels": data.get("labels", []), "timestamp": data.get("timestamp", 0)}

            except Exception as e:
                self.connected = False
                print(f"[Telemetry] Stream disconnected: {e}. Reconnecting in 2s...")
                await asyncio.sleep(2)


def get_latest_telemetry() -> Dict:
    """Thread-safe retrieval of the latest telemetry data."""
    with telemetry_lock:
        return latest_telemetry.copy()


def main():
    if not API_KEY:
        print("Error: GOOGLE_API_KEY not found in environment.")
        return

    # 1. Start Telemetry Stream
    stream = TelemetryStream()
    stream.start()
    print("Waiting for telemetry connection...")
    while not stream.connected:
        time.sleep(0.5)
    print("Telemetry active.")

    # 2. Initialize Gemini Client
    client = genai.Client(api_key=API_KEY)

    # 3. Configure Chat Session
    # System prompt to define the agent's persona and capabilities
    system_instruction = """
    You are a Robot Agent controlling a JetBot. 
    You have access to vision tools (not direct video) and movement tools to navigate the environment.
    
    SENSOR DATA AVAILABLE:
    - Ultrasonic distance sensor: Reports distance to nearest obstacle in front of the robot.
      - distance_m: Distance in meters (typical range 0.02m to 4.0m)
      - distance_cm: Same value in centimeters for convenience
      - Use this to avoid collisions and gauge proximity to objects
    - Vision detections: Current objects detected by the vision system (if labels are set)
    
    Your goal is to follow user instructions autonomously.
    
    FRAMEWORK:
    1. SENSE: Check telemetry (ultrasonic distance, current detections).
    2. OBSERVE: Use vision tools if you need to see (set_vision_labels, scan_surroundings, rotate_until_centered).
    3. DECIDE: Choose the next best action based on sensor data and mission goal.
    4. ACT: Call movement tools to navigate.
    
    GUIDELINES:
    - Use ultrasonic readings to avoid obstacles. If distance < 0.3m, the robot will stop automatically and return a "safety" status message.
    - To find an object: call 'set_vision_labels' first, then 'scan_surroundings' or 'rotate_until_centered'.
    - 'rotate_until_centered' is excellent for aligning with a target before driving to it.
    - 'move_distance' takes meters. 0.5m is a standard safe step. 0.2m for precision.
    - Always check ultrasonic distance before moving forward.
    - When task is complete, report success clearly in your response so the user knows you're done.
    """

    chat = client.chats.create(
        model=MODEL_ID,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[move_distance_tool, rotate_robot_tool, move_arc_tool, stop_robot_tool, set_vision_labels_tool, scan_surroundings_tool, rotate_until_centered_tool, get_bounding_box_percentage_tool],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=False,
                maximum_remote_calls=5,  # Allow up to 5 chained tool calls per turn
            ),
        ),
    )

    print("\n" + "=" * 40)
    print("🤖 GEMINI LIVE AGENT READY")
    print("=" * 40)

    user_input = input("\nCommand: ")  # Initial command

    while True:
        try:
            # 1. Get Telemetry Context
            telemetry = get_latest_telemetry()

            # Format telemetry as context for Gemini
            context_msg = f"""
            [TELEMETRY UPDATE]
            Ultrasonic Distance: {telemetry.get("ultrasonic", {}).get("distance_m", "N/A")}m ({telemetry.get("ultrasonic", {}).get("distance_cm", "N/A")}cm)
            Current Detections: {telemetry.get("num_detections", 0)} objects
            Active Labels: {", ".join(telemetry.get("labels", [])) if telemetry.get("labels") else "None"}
            Detected Objects: {", ".join([d.get("class_name", "unknown") for d in telemetry.get("detections", [])]) if telemetry.get("detections") else "None"}
            
            User Command: {user_input}
            """

            # 2. Send to Gemini (Text only, no video)
            print("\nThinking...")
            response = chat.send_message(message=context_msg)

            # 3. Display Response
            print(f"\n🤖 Gemini: {response.text}")

            # No automatic mission completion - user decides when to stop

            # For continuous autonomous behavior:
            # The agent will keep looping with updated telemetry
            user_input = input("\n[VOICE] Speak or type next command (Enter=continue, q=quit): ")

            if not user_input:
                # Autonomous mode: continue with updated telemetry
                user_input = "Check sensors and continue with the mission."
            elif user_input.lower() in ["exit", "quit", "q"]:
                break

            time.sleep(0.5)  # Brief pause before next iteration

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error in loop: {e}")
            time.sleep(1)

    # Cleanup
    stream.running = False
    stop_robot_tool()
    print("Agent shut down.")


if __name__ == "__main__":
    main()
