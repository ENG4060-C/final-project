#!/usr/bin/env python3
"""
Calibration Test Script

Tests rotations and movements at different speeds:
- Rotations: 90° x4, 180° x2, 360° x1
- Movements: forward and backward at specified distances
- Tests at speeds: 0.5, 0.75, and 1.0
"""

import time
from controls import RobotController

print("="*60)
print("CALIBRATION TESTS")
print("="*60)

# Initialize robot controller
print("\nInitializing robot controller...")
controller = RobotController()
print("Robot controller initialized\n")

def run_rotation_tests(speed: float):
    """Run rotation tests: 90° x4, 180° x2, 360° x1"""
    print(f"\n{'='*60}")
    print(f"ROTATION TESTS at speed {speed}")
    print("="*60)
    
    # Rotate 90 degrees 4 times
    print("\nRotating 90° four times:")
    for i in range(4):
        print(f"  Rotation {i+1}/4:")
        controller.rotate(90, speed)
        if i < 3:
            print("  Pausing 1 second...")
            time.sleep(1)
    
    print("\nCompleted 4x 90° rotations")
    time.sleep(2)
    
    # Rotate 180 degrees twice
    print("\nRotating 180° two times:")
    for i in range(2):
        print(f"  Rotation {i+1}/2:")
        controller.rotate(180, speed)
        if i < 1:
            print("  Pausing 1 second...")
            time.sleep(1)
    
    print("\nCompleted 2x 180° rotations")
    time.sleep(2)
    
    # Rotate 360 degrees once
    print("\nRotating 360° once:")
    controller.rotate(360, speed)
    print("\nCompleted 1x 360° rotation")
    time.sleep(2)

def run_movement_tests(speed: float, distance: float):
    """Run movement tests: forward and backward at specified distance"""
    print(f"\n{'='*60}")
    print(f"MOVEMENT TESTS at speed {speed}, distance {distance}m")
    print("="*60)
    
    # Move forward
    print(f"\nMoving forward {distance}m:")
    controller.move_distance(distance, speed)
    print("  Pausing 1 second...")
    time.sleep(1)
    
    # Move backward
    print(f"\nMoving backward {distance}m:")
    controller.move_distance(-distance, speed)
    print("  Pausing 1 second...")
    time.sleep(1)
    
    print(f"\nCompleted forward/backward movements at {distance}m")

# Test sequence at speed 0.5
print("\n" + "="*60)
print("TEST SEQUENCE 1: Speed 0.5")
print("="*60)
run_rotation_tests(0.5)
run_movement_tests(0.5, 0.25)
time.sleep(2)

# Test sequence at speed 0.75
print("\n" + "="*60)
print("TEST SEQUENCE 2: Speed 0.75")
print("="*60)
run_rotation_tests(0.75)
run_movement_tests(0.75, 0.25)
time.sleep(2)

# Test sequence at speed 1.0 with 0.5m distance
print("\n" + "="*60)
print("TEST SEQUENCE 3: Speed 1.0, Distance 0.5m")
print("="*60)
run_rotation_tests(1.0)
run_movement_tests(1.0, 0.5)

print("\n" + "="*60)
print("ALL CALIBRATION TESTS COMPLETE")
print("="*60)
print("\nNote: Observe robot movement for:")
print("  - Smooth acceleration and deceleration")
print("  - Accurate rotations (90°, 180°, 360°)")
print("  - Straight movement (left wheel offset compensates for imbalance)")
print("  - Consistent behavior across different speeds")

