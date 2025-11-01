#!/usr/bin/env python3
"""
Queue Movement Test Script

Tests the queue_movement function by:
- Drawing a square with side length 0.1m
- Drawing a full circle with radius 0.1m using move_arc
"""

import time
from controls import RobotController

print("="*60)
print("QUEUE MOVEMENT TESTS")
print("="*60)

# Initialize robot controller
print("\nInitializing robot controller...")
controller = RobotController()
print("Robot controller initialized\n")

# Draw a square with side length 0.1m
print("="*60)
print("TEST 1: Drawing a square (0.1m sides)")
print("="*60)

square_movements = [
    (controller.move_distance, 0.1),
    (controller.rotate, 90),
    (controller.move_distance, 0.1),
    (controller.rotate, 90),
    (controller.move_distance, 0.1),
    (controller.rotate, 90),
    (controller.move_distance, 0.1),
    (controller.rotate, 90),
]

print("\nExecuting square movements...")
controller.queue_movement(square_movements)
print("\nSquare drawing complete!")
time.sleep(2)

# Draw a full circle with radius 0.1m
print("\n" + "="*60)
print("TEST 2: Drawing a full circle (radius 0.1m)")
print("="*60)

circle_movements = [
    (controller.move_arc, 0.1, 360),
]

print("\nExecuting circle movement...")
controller.queue_movement(circle_movements)
print("\nCircle drawing complete!")

print("\n" + "="*60)
print("ALL QUEUE MOVEMENT TESTS COMPLETE")
print("="*60)

