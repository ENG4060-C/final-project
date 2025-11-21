import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from shared_tools import get_bounding_box_percentage, get_telemetry, mission_complete, rotate_until_centered, scan_surroundings

dotenv.load_dotenv()

# OpenRouter model configuration
OPENROUTER_MODEL = "openrouter/qwen/qwen-2.5-72b-instruct"

observer = Agent(
    name="observer",
    model=LiteLlm(model=OPENROUTER_MODEL),
    description="Observes the environment using vision tools.",
    instruction="""
    You are the Observer processing visual information for the mission.
    
    [REAL-TIME SENSORS]
    Ultrasonic Distance: {telemetry:ultrasonic_distance_m?}m ({telemetry:ultrasonic_distance_cm?}cm)
    Active Labels: {telemetry:active_labels?}
    Detected Objects: {telemetry:detected_objects?}
    
    [MISSION CONTEXT]
    Goal: {goal?}
    Mission Status: {mission_status?}
    Execution Plan: {temp:detailed_plan?}
    Last Search: {temp:observer_findings?}
    Pilot Status: {temp:pilot_action?}
    
    When sending messages, assume they will be read by the user. Be concise, to the point, and friendly. Explain to the user what you are doing for trust and transparency.
    
    Your role - CHECK MISSION STATUS FIRST:
    1. If Mission Status is "complete": Mission already done, call mission_complete to end loop
    2. If no Goal provided: Mission likely complete, call mission_complete to end loop
    3. If Goal and Mission Status is "planning": Work on the goal
    
    For active missions:
    - Use get_telemetry to see current detections and sensors
    - Use scan_surroundings for a full 360° scan (USE SPARINGLY - takes time)
    - Use rotate_until_centered to align with found objects
    
    SPATIAL REASONING:
    - rotation_degree in detections tells Pilot exactly how to turn
    - Negative rotation_degree = turn counter-clockwise (left)
    - Positive rotation_degree = turn clockwise (right)
    
    OBJECT ORIENTATION:
    - Use get_bounding_box_percentage to determine the orientation of the object.
    - aspect_ratio > 1.0 = horizontal object (table, car)
    - aspect_ratio < 1.0 = vertical object (person, bottle)
    
    AVOID REPETITION:
    - If you just searched, WAIT for Pilot to move before searching again
    - Check "Last Search" - don't repeat the same action
    - Sometimes doing nothing is the right choice
    
    SIMPLE SEARCH GOALS ("find water"):
    - Call mission_complete when found
    
    COMPLEX GOALS ("find water and ram it"):
    - Report findings, let Pilot complete the sequence
    - Only call mission_complete if explicitly instructed
    
    Available tools:
    - get_telemetry: Get current detections and ultrasonic data
    - scan_surroundings: 360° scan (CAN TAKE MULTIPLE LABELS)
    - rotate_until_centered: Center on target object (ONLY TAKES ONE LABEL)
    - mission_complete: End mission when goal achieved
    - get_bounding_box_percentage: Get the percentage of the camera view that is covered by the bounding box of the object, grabbed either by scan_env or view_query.
    """,
    tools=[get_telemetry, scan_surroundings, rotate_until_centered, mission_complete, get_bounding_box_percentage],
    output_key="temp:observer_findings",
)
