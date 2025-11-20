from google.adk.agents import LoopAgent, SequentialAgent

from .director.agent import director
from .observer.agent import observer
from .pilot.agent import pilot

# Execution loop: Observer and Pilot run in parallel until mission complete
execution_loop = LoopAgent(
    name="execution_loop",
    sub_agents=[
        observer,
        pilot,
    ],
    max_iterations=50,
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
