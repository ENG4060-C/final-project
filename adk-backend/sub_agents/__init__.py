from google.adk.agents import LoopAgent, SequentialAgent
from google.genai import types as genai_types

from .director.agent import director
from .observer.agent import observer
from .pilot.agent import pilot

# Guard: stop the loop immediately if mission is already complete
def _stop_if_mission_complete(callback_context):
    try:
        status = str(callback_context.state.get("mission_status", "")).lower()
    except Exception:
        status = ""
    if status == "complete":
        # Escalate to tell LoopAgent to stop before invoking sub-agents
        callback_context._event_actions.escalate = True  # type: ignore[attr-defined]
        # Return empty content so an event is emitted (UI ignores empty parts)
        return genai_types.Content(parts=[])
    return None

# Execution loop: Observer and Pilot run until mission complete
execution_loop = LoopAgent(
    name="execution_loop",
    sub_agents=[observer, pilot],
    max_iterations=50,
    before_agent_callback=_stop_if_mission_complete,
)

# Complete system: Director initializes → Execution loop until done
autonomous_robot_system = SequentialAgent(
    name="autonomous_robot_system",
    sub_agents=[
        director,
        execution_loop,
    ],
)


__all__ = [
    "director",
    "observer",
    "pilot",
    "execution_loop",
    "autonomous_robot_system",
]
