"""
Tools for robot control and vision processing.
Connects to the JetBot API (port 8000) to execute movement and vision commands.
"""

import datetime
from typing import Any, Dict, List, Optional

import requests
from google.adk.tools import FunctionTool, ToolContext

# Configuration
_ROBOT_API_BASE = "http://localhost:8000"


# ----------------------------
# Mission control helpers
# ----------------------------
def initialize_mission_tool(goal: str, detailed_plan: str, tool_context: ToolContext) -> dict:
    """Initialize mission state with goal, status, and create execution plan.

    Used by Director to set up complex multi-step missions.

    Args:
        goal (str): The user's goal for the mission.
        detailed_plan (str): Detailed step-by-step plan for Observer and Pilot.
        tool_context: ADK context for state management.

    Returns:
        dict: Mission initialization status.
    """
    tool_context.state["goal"] = goal
    tool_context.state["mission_start_time"] = datetime.datetime.now().isoformat()
    tool_context.state["temp:detailed_plan"] = detailed_plan
    tool_context.state["mission_status"] = "planning"

    return {"status": "Mission initialized with plan", "goal": goal, "mission_status": "planning", "detailed_plan": detailed_plan}


initialize_mission = FunctionTool(func=initialize_mission_tool)


def mission_complete_tool(reason: str, tool_context: ToolContext) -> dict:
    """Terminate the execution loop when the mission is complete.

    Args:
        reason (str): Description of why the mission is considered complete (e.g., "Red bottle found and centered").

    Returns:
        dict: Status of mission completion.
    """
    # Update mission status in state
    tool_context.state["mission_status"] = "complete"

    # Signal to terminate the agent loop
    tool_context.actions.escalate = True

    return {"status": "Mission complete", "reason": reason, "mission_status": "complete", "loop_terminated": True}


mission_complete = FunctionTool(func=mission_complete_tool)


# ----------------------------
# Robot Movement Tools
# ----------------------------


def move_distance_tool(distance_m: float, speed: float = 0.5) -> dict:
    """Move the robot forward or backward by a specific distance.

    SPATIAL REASONING:
    - Positive distance (> 0) moves FORWARD.
    - Negative distance (< 0) moves BACKWARD.
    - 0.5 meters is roughly 1.5 feet.
    - Use lower speeds (0.3-0.5) for precision, higher speeds (0.6-1.0) for distance.

    Args:
        distance_m (float): Distance to move in meters (-10.0 to 10.0).
        speed (float, optional): Motor speed (0.3 to 1.0). Defaults to 0.5.

    Returns:
        dict: Result of the movement command, including start/end sensor readings.
    """
    # Validate and clamp parameters
    distance_m = float(distance_m)
    speed = float(speed)

    # Clamp to valid ranges
    distance_m = max(-10.0, min(10.0, distance_m))
    speed = max(0.3, min(1.0, speed))

    print(f"[ADK-Tool] Moving distance: {distance_m}m at speed {speed}")
    url = f"{_ROBOT_API_BASE}/move/distance"
    payload = {"distance_m": distance_m, "robot_speed": speed}

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        error_detail = str(e)
        if hasattr(e, "response") and e.response is not None:
            try:
                error_detail = e.response.json()
            except:
                error_detail = e.response.text
        return {"error": f"Failed to move distance: {error_detail}"}


move_distance = FunctionTool(func=move_distance_tool)


def rotate_robot_tool(angle_degrees: float, speed: float = 0.5) -> dict:
    """Rotate the robot in place by a specific angle.

    SPATIAL REASONING:
    - Positive angle (> 0) rotates COUNTER-CLOCKWISE (Left).
    - Negative angle (< 0) rotates CLOCKWISE (Right).
    - 90 degrees is a quarter turn. 180 turns around. 360 does a full spin.

    Args:
        angle_degrees (float): Angle to rotate in degrees.
        speed (float, optional): Motor speed (0.3 to 1.0). Defaults to 0.5.

    Returns:
        dict: Result of the rotation command.
    """
    print(f"[ADK-Tool] Rotating: {angle_degrees} deg at speed {speed}")
    url = f"{_ROBOT_API_BASE}/move/rotate"
    payload = {"angle_degrees": angle_degrees, "robot_speed": speed}

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": f"Failed to rotate: {str(e)}"}


rotate_robot = FunctionTool(func=rotate_robot_tool)


def move_arc_tool(radius_m: float, angle_degrees: float, speed: float = 0.5) -> dict:
    """Move the robot in an arc (curve).

    Useful for navigating around obstacles or smooth turning.

    Args:
        radius_m (float): Radius of the turn in meters.
                          - Positive (+) for LEFT turn radius.
                          - Negative (-) for RIGHT turn radius.
        angle_degrees (float): Distance to travel along the arc in degrees.
                               - Positive (+) to move FORWARD along arc.
                               - Negative (-) to move BACKWARD along arc.
        speed (float, optional): Motor speed (0.3 to 1.0). Defaults to 0.5.

    Returns:
        dict: Result of the movement.
    """
    print(f"[ADK-Tool] Moving arc: radius {radius_m}m, angle {angle_degrees} deg")
    url = f"{_ROBOT_API_BASE}/move/arc"
    payload = {"radius_m": radius_m, "angle_degrees": angle_degrees, "robot_speed": speed}

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": f"Failed to execute arc move: {str(e)}"}


move_arc = FunctionTool(func=move_arc_tool)


def stop_robot_tool() -> dict:
    """Immediately stop the robot's motors.

    Use this for emergency stops or to ensure the robot is stationary before scanning.

    Returns:
        dict: Status of the stop command.
    """
    print("[ADK-Tool] Stopping robot")
    url = f"{_ROBOT_API_BASE}/stop"

    try:
        response = requests.post(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": f"Failed to stop robot: {str(e)}"}


stop_robot = FunctionTool(func=stop_robot_tool)


# ----------------------------
# Telemetry Query Tool
# ----------------------------


def get_telemetry_tool() -> dict:
    """Get current real-time sensor readings from the robot.

    Returns:
        dict: Current telemetry including:
        - ultrasonic: {"distance_m": float, "distance_cm": float}
        - detections: List of currently detected objects with bounding boxes
        - num_detections: Number of objects detected
        - labels: Currently active vision labels
    """
    print("[ADK-Tool] Querying telemetry")
    yolo_url = "http://localhost:8002/current-detections"

    try:
        response = requests.get(yolo_url)
        response.raise_for_status()
        data = response.json()

        ultrasonic = data.get("ultrasonic", {})
        print(f"[ADK-Tool] Ultrasonic: {ultrasonic.get('distance_m', 'N/A')}m, Detections: {data.get('num_detections', 0)}")

        return data
    except requests.RequestException as e:
        return {"error": f"Failed to get telemetry: {str(e)}"}


get_telemetry = FunctionTool(func=get_telemetry_tool)


# ----------------------------
# Vision & Scanning Tools
# ----------------------------
def set_vision_labels_tool(labels: List[str]) -> dict:
    """Configure the vision system (YOLO-E) to detect specific objects.

    Always call this BEFORE scanning or searching if you are looking for new objects.
    The model performs open-vocabulary detection based on these text prompts.

    Args:
        labels (List[str]): List of object names to detect (e.g., ["bottle", "person", "red cup"]).

    Returns:
        dict: Confirmation of labels set.
    """
    print(f"[ADK-Tool] Setting vision labels: {labels}")
    url = f"{_ROBOT_API_BASE}/vision/labels"
    payload = {"labels": labels}

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": f"Failed to set vision labels: {str(e)}"}


set_vision_labels = FunctionTool(func=set_vision_labels_tool)


def scan_surroundings_tool(labels: Optional[List[str]] = None) -> dict:
    """Scan the environment by rotating the robot and detecting objects in various sectors.

    The robot will rotate 360 degrees in steps, cataloging objects found in each sector.

    Args:
        labels (List[str], optional): Specific objects to look for during this scan.
                                      If provided, temporarily updates vision labels.
                                      If None, uses currently set labels.

    Returns:
        dict: A mapping of sectors (e.g., "0-45", "45-90") to lists of objects found.
              Example: {"0-45": ["bottle"], "90-135": ["person", "chair"]}
    """
    print(f"[ADK-Tool] Scanning surroundings (Labels: {labels})")
    url = f"{_ROBOT_API_BASE}/vision/scan"
    # Payload can be just the list, or dict {"labels": []} based on API.
    # API accepts body as list or dict with 'labels'.
    payload = {"labels": labels} if labels else {}

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": f"Failed to scan environment: {str(e)}"}


scan_surroundings = FunctionTool(func=scan_surroundings_tool)


def rotate_until_centered_tool(target_object: str, timeout_seconds: float = 20.0) -> dict:
    """Rotate the robot until a specific object is centered in the camera view.

    Useful for aligning the robot before approaching an object.
    Note: This tool automatically sets the vision label to 'target_object'.

    Args:
        target_object (str): The name of the object to center (e.g., "bottle").
        timeout_seconds (float, optional): Max time to try centering. unused by API but good for documentation.

    Returns:
        dict: Result containing 'status' ("found" or "not_found") and movement info.
    """
    print(f"[ADK-Tool] Rotating until '{target_object}' is centered")
    url = f"{_ROBOT_API_BASE}/vision/rotate_until_object_center"

    # API expects 'items' list.
    payload = {
        "items": [target_object],
        "robot_speed": 0.75,
        "center_threshold": 200.0,  # pixels from center
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()

        if result.get("status") == "found":
            print(f"[ADK-Tool] Centered on {target_object}.")
        else:
            print(f"[ADK-Tool] Failed to center on {target_object}.")

        return result
    except requests.RequestException as e:
        return {"error": f"Failed to execute rotate_until_centered: {str(e)}"}


rotate_until_centered = FunctionTool(func=rotate_until_centered_tool)


# ----------------------------
# Utility Calculation Tools
# ----------------------------
def get_bounding_box_percentage_tool(bbox: List[int]) -> float:
    """Calculate the percentage of the camera view covered by a bounding box.

    Args:
        bbox (List[int]): Bounding box coordinates [x1, y1, x2, y2].

    Returns:
        float: Percentage of image area (0.0 to 100.0).
    """
    # Standard JetBot camera resolution assumed 1640x1232 or similar aspect ratio.
    # Adjust roughly to the resolution used by YOLO inference if downsampled.
    # Assuming default capture resolution for calculation context.
    CAMERA_WIDTH = 1280
    CAMERA_HEIGHT = 720
    CAMERA_AREA = CAMERA_WIDTH * CAMERA_HEIGHT

    if not bbox or len(bbox) != 4:
        return 0.0

    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    area = width * height

    return (area / CAMERA_AREA) * 100.0


get_bounding_box_percentage = FunctionTool(func=get_bounding_box_percentage_tool)
