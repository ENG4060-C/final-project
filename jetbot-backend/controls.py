# FastAPI server exposing Jetbot Functionality
import math
import threading
import time
from typing import Optional, Dict, List, Tuple, Union, Callable

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from jetbot import Robot, Camera
import cv2

# Hardware Configuration
IMAGE_WIDTH = 1640
IMAGE_HEIGHT = 1232
I2C_BUS = 7
LEFT_MOTOR_CHANNEL = 1
RIGHT_MOTOR_CHANNEL = 2
MAX_MOTOR_VALUE = 1.0         
MIN_MOTOR_VALUE = 0.3
STATIC_FRICTION_THRESHOLD = 0.30

# Calibrated values (from testing)
MOTOR_SPEED_FACTOR = 0.1827
LEFT_MOTOR_OFFSET = 0.0085
WHEELBASE_M = 0.0540
ACCEL_DECEL_RATIO = 0.25
ACCEL_DECEL_STEPS = 5
MIN_ACCEL_DECEL_TIME = 0.15
OSHOOT_CORRECTION_START = 0.03
OSHOOT_CORRECTION_SLOPE = 0.00005
OSHOOT_CORRECTION_MAX = 0.07

class RobotController:
    """
    Controller for JetBot hardware providing motor and camera control.
    """
    
    def __init__(self):
        """Initialize robot and camera hardware."""
        print("Initializing RobotController...")
        self.robot = Robot(
            i2c_bus=I2C_BUS, 
            left_motor_channel=LEFT_MOTOR_CHANNEL, 
            right_motor_channel=RIGHT_MOTOR_CHANNEL
        )
        self.camera = Camera(width=IMAGE_WIDTH, height=IMAGE_HEIGHT)
    
    def _smooth_stop(self, left_motor_start: float, right_motor_start: float, 
                     deceleration_time: float):
        """
        Gradually reduce motor speed to zero over the deceleration period.
        
        Args:
            left_motor_start: Initial left motor value
            right_motor_start: Initial right motor value
            deceleration_time: Time in seconds for deceleration
        """
        if deceleration_time <= 0:
            self.robot.stop()
            return
        
        # Calculate step time
        step_time = deceleration_time / ACCEL_DECEL_STEPS
        
        # Get absolute values and direction signs
        left_abs = abs(left_motor_start)
        right_abs = abs(right_motor_start)
        left_dir = 1 if left_motor_start >= 0 else -1
        right_dir = 1 if right_motor_start >= 0 else -1
        
        # Gradually reduce speed from full speed to zero
        # Use a smooth linear ramp
        for step in range(ACCEL_DECEL_STEPS):
            # Calculate progress: 1.0 (full speed) down to 0.0 (stopped)
            progress = 1.0 - (step / ACCEL_DECEL_STEPS)
            
            # Calculate motor values (linear ramp)
            left_val = left_abs * progress * left_dir
            right_val = right_abs * progress * right_dir
            
            # For very small values, just set to zero to avoid motor jitter
            if abs(left_val) < 0.05:
                left_val = 0.0
            if abs(right_val) < 0.05:
                right_val = 0.0
            
            self.robot.left_motor.value = left_val
            self.robot.right_motor.value = right_val
            time.sleep(step_time)
        
        # Final stop to ensure motors are completely off
        self.robot.stop()
    
    def _smooth_start(self, left_motor_target: float, right_motor_target: float, 
                     acceleration_time: float, left_offset: float = 0.0):
        """
        Gradually increase motor speed from zero to target speed over the acceleration period.
        
        Args:
            left_motor_target: Target left motor value
            right_motor_target: Target right motor value
            acceleration_time: Time in seconds for acceleration
            left_offset: Constant offset to apply to left motor during acceleration (default: 0.0)
                        This offset is applied as a constant value throughout acceleration, not proportional.
        """
        if acceleration_time <= 0:
            self.robot.left_motor.value = left_motor_target
            self.robot.right_motor.value = right_motor_target
            return
        
        # Calculate step time
        step_time = acceleration_time / ACCEL_DECEL_STEPS
        
        # Calculate base motor values (target values without offset)
        base_left_motor = left_motor_target - left_offset
        base_right_motor = right_motor_target
        
        # Get absolute values and direction signs for base values
        left_base_abs = abs(base_left_motor)
        right_abs = abs(base_right_motor)
        left_dir = 1 if base_left_motor >= 0 else -1
        right_dir = 1 if right_motor_target >= 0 else -1
        
        # Get offset direction (same as left motor direction)
        offset_dir = left_dir if base_left_motor != 0 else (1 if left_offset >= 0 else -1)
        
        # Calculate the range we need to ramp over
        start_motor_left = min(STATIC_FRICTION_THRESHOLD, left_base_abs)
        start_motor_right = min(STATIC_FRICTION_THRESHOLD, right_abs)
        
        # Gradually increase speed from static friction threshold to target speed
        for step in range(ACCEL_DECEL_STEPS):
            # Calculate progress: 0.0 (at start) up to 1.0 (target speed)
            progress = (step + 1) / ACCEL_DECEL_STEPS
            
            # Calculate base motor values (ramp from start to target)
            left_val = (start_motor_left + (left_base_abs - start_motor_left) * progress) * left_dir
            right_val = (start_motor_right + (right_abs - start_motor_right) * progress) * right_dir
            
            # Apply constant offset to left motor throughout acceleration
            if abs(left_offset) > 0:
                left_val += left_offset * offset_dir
                
                # Clamp to valid range
                if left_val > 1.0:
                    overflow = left_val - 1.0
                    left_val = 1.0
                    # If we hit max, reduce right motor to compensate
                    right_val = max(0.0, right_val - overflow) * right_dir
                elif left_val < -1.0:
                    overflow = abs(left_val + 1.0)
                    left_val = -1.0
                    right_val = min(0.0, right_val + overflow) * right_dir
            
            self.robot.left_motor.value = left_val
            self.robot.right_motor.value = right_val
            time.sleep(step_time)
        
        # Final set to ensure we reach exact target values
        self.robot.left_motor.value = left_motor_target
        self.robot.right_motor.value = right_motor_target
    
    def move_distance(self, distance_m: float, robot_speed: float = 0.5) -> Dict[str, float]:
        """
        Move robot forward/backward for approximately the specified distance.
        
        Time-based estimation without encoder feedback. 
        Actual distance may vary ±20% due to wheel slip, battery, surface.
        
        Args:
            distance_m: Distance in meters (+ = forward, - = backward)
            robot_speed: Motor speed value 0.0 to 1.0 (default: 0.5 = half speed)
        
        """
        PRINT_PREFIX = "[MOVE_DISTANCE]"
        PREFIX_COLOR = "\033[92m"
        PREFIX_RESET = "\033[0m"
        
        # Determine direction from distance sign
        direction = 1 if distance_m >= 0 else -1
        distance_abs = abs(distance_m)
        
        # Clamp motor speed to valid range (0.0 to 1.0)
        motor_value = max(MIN_MOTOR_VALUE, min(abs(robot_speed), MAX_MOTOR_VALUE))
        
        # Calculate actual speed and duration from motor value
        actual_speed_m_s = motor_value * MOTOR_SPEED_FACTOR
        duration_s = distance_abs / actual_speed_m_s
        
        # Calculate acceleration and deceleration times
        acceleration_time = duration_s * ACCEL_DECEL_RATIO
        deceleration_time = duration_s * ACCEL_DECEL_RATIO
        
        # Adjust constant duration to account for acceleration and deceleration
        constant_duration = duration_s - (acceleration_time * 0.5) - (deceleration_time * 0.5)
        
        # Ensure constant duration is not negative (for very short movements)
        if constant_duration < 0:
            total_phase_time = acceleration_time + deceleration_time
            if total_phase_time > 0:
                scale_factor = duration_s / total_phase_time
                acceleration_time *= scale_factor * 0.5
                deceleration_time *= scale_factor * 0.5
                constant_duration = 0.0
            else:
                acceleration_time = 0.0
                deceleration_time = 0.0
                constant_duration = duration_s
        
        # Prepare signed motor value for direction
        motor_value_signed = motor_value * direction
        
        # Calculate base motor values and offset separately
        base_left_motor = motor_value * direction
        base_right_motor = motor_value * direction
        
        # Calculate offset to apply (accounting for overflow)
        if direction > 0:
            offset_to_apply = LEFT_MOTOR_OFFSET
            
            # Overflow case: reduce offset by overflow amount
            if motor_value + LEFT_MOTOR_OFFSET > 1.0:
                overflow = motor_value + LEFT_MOTOR_OFFSET - 1.0
                offset_to_apply = LEFT_MOTOR_OFFSET - overflow
        else:
            offset_to_apply = -LEFT_MOTOR_OFFSET
            
            # Overflow case: reduce offset by overflow amount
            if -motor_value - LEFT_MOTOR_OFFSET < -1.0:
                overflow = abs(-motor_value - LEFT_MOTOR_OFFSET + 1.0)
                offset_to_apply = -LEFT_MOTOR_OFFSET + overflow
        
        # Calculate final motor values with offset (for constant speed phase)
        left_motor = base_left_motor + offset_to_apply
        right_motor = base_right_motor
        
        # Handle overflow by adjusting right motor
        if left_motor > 1.0:
            overflow = left_motor - 1.0
            left_motor = 1.0
            right_motor = max(0.0, motor_value - overflow) * direction
        elif left_motor < -1.0:
            overflow = abs(left_motor + 1.0)
            left_motor = -1.0
            right_motor = min(0.0, -motor_value + overflow) * direction
        
        print(f"{PREFIX_COLOR}{PRINT_PREFIX} Moving {distance_m:+.3f}m at {actual_speed_m_s:.3f} m/s "
              f"(robot_speed={motor_value_signed:+.2f}, duration={duration_s:.2f}s, "
              f"accel={acceleration_time:.2f}s, constant={constant_duration:.2f}s, "
              f"decel={deceleration_time:.2f}s){PREFIX_RESET}")
        
        # Smooth acceleration phase with constant offset applied throughout
        self._smooth_start(left_motor, right_motor, acceleration_time, left_offset=offset_to_apply)
        
        # Constant speed phase
        if constant_duration > 0:
            time.sleep(constant_duration)
        
        # Smooth deceleration phase
        self._smooth_stop(left_motor, right_motor, deceleration_time)
    
    def rotate(self, angle_degrees: float, robot_speed: float = 0.4):
        """Rotate robot in place by specified angle."""
        PRINT_PREFIX = "[ROTATE]"
        PREFIX_COLOR = "\033[95m"
        PREFIX_RESET = "\033[0m"
        
        # Clamp motor speed to valid range (0.0 to 1.0)
        motor_value = max(MIN_MOTOR_VALUE, min(abs(robot_speed), MAX_MOTOR_VALUE))
        
        # Calculate actual speed and duration from motor value
        actual_speed_m_s = motor_value * MOTOR_SPEED_FACTOR
        angle_rad = math.radians(abs(angle_degrees))
        wheel_distance_m = angle_rad * WHEELBASE_M / 2.0
        duration_s = wheel_distance_m / actual_speed_m_s
        
        # Apply overshoot correction for angles > 90°
        angle_abs = abs(angle_degrees)
        if angle_abs > 90:
            overshoot_pct = OSHOOT_CORRECTION_START + (angle_abs - 90) * OSHOOT_CORRECTION_SLOPE
            overshoot_pct = min(overshoot_pct, OSHOOT_CORRECTION_MAX)
            duration_s *= (1.0 - overshoot_pct)
        
        # Calculate deceleration time (no smooth start for rotation)
        deceleration_time = max(MIN_ACCEL_DECEL_TIME, duration_s * ACCEL_DECEL_RATIO)
        
        # Calculate constant duration accounting for deceleration only
        constant_duration = duration_s - (deceleration_time * 0.5)
        
        # Ensure constant duration is not negative (for very short rotations)
        if constant_duration < 0:
            constant_duration = duration_s * 0.1
            deceleration_time = duration_s - constant_duration
        
        # Set motor values based on angle direction
        if angle_degrees > 0:
            left_motor = motor_value
            right_motor = -motor_value
        else:
            left_motor = -motor_value
            right_motor = motor_value
        
        print(f"{PREFIX_COLOR}{PRINT_PREFIX} Rotating {angle_degrees:+.1f}° at {actual_speed_m_s:.3f} m/s "
              f"(robot_speed={motor_value:.2f}, constant={constant_duration:.2f}s, decel={deceleration_time:.2f}s){PREFIX_RESET}")
        
        # Start both motors simultaneously from static friction threshold
        start_value = min(STATIC_FRICTION_THRESHOLD, abs(motor_value))
        left_dir = 1 if left_motor >= 0 else -1
        right_dir = 1 if right_motor >= 0 else -1
        
        # Start both motors at threshold simultaneously
        self.robot.left_motor.value = start_value * left_dir
        self.robot.right_motor.value = start_value * right_dir
        time.sleep(0.05)  # Brief pause to ensure both motors start
        
        # Then set to target speed
        self.robot.left_motor.value = left_motor
        self.robot.right_motor.value = right_motor
        
        # Constant speed phase
        if constant_duration > 0:
            time.sleep(constant_duration)
        
        # Smooth deceleration phase
        self._smooth_stop(left_motor, right_motor, deceleration_time)
    
    def move_arc(self, radius_m: float, angle_degrees: float, robot_speed: float = 0.5):
        """
        Move robot in an arc (turning while moving forward/backward).
        
        Uses differential drive kinematics to follow an arc path.
        
        Args:
            radius_m: Turn radius in meters. Positive = left turn, negative = right turn.
            angle_degrees: Angle to travel along the arc in degrees.
                          Positive = forward along arc, negative = backward along arc
            robot_speed: Motor speed value 0.0 to 1.0 (default: 0.5)
        """
        PRINT_PREFIX = "[MOVE_ARC]"
        PREFIX_COLOR = "\033[94m"
        PREFIX_RESET = "\033[0m"
        
        # Clamp motor speed to valid range
        motor_value = max(MIN_MOTOR_VALUE, min(abs(robot_speed), MAX_MOTOR_VALUE))
        
        # Determine direction from angle sign
        direction = 1 if angle_degrees >= 0 else -1
        angle_abs = abs(angle_degrees)
        angle_rad = math.radians(angle_abs)
        
        # Calculate differential drive speeds for arc movement
        min_radius = WHEELBASE_M / 2.0
        radius_abs = abs(radius_m)
        if radius_abs < min_radius:
            radius_abs = min_radius
        
        # Calculate arc distance (distance along the arc path) using effective radius
        effective_radius = radius_abs
        arc_distance_m = effective_radius * angle_rad
        
        # Calculate actual speed and duration from motor value
        actual_speed_m_s = motor_value * MOTOR_SPEED_FACTOR
        duration_s = arc_distance_m / actual_speed_m_s
        
        # Calculate deceleration time
        deceleration_time = max(MIN_ACCEL_DECEL_TIME, duration_s * ACCEL_DECEL_RATIO)
        
        # Calculate constant duration accounting for deceleration only
        constant_duration = duration_s - (deceleration_time * 0.5)
        
        # Ensure constant duration is not negative
        if constant_duration < 0:
            constant_duration = duration_s * 0.1
            deceleration_time = duration_s - constant_duration
        
        if radius_m > 0:
            # Left turn: left wheel is inner (slower), right wheel is outer (faster)
            inner_radius = radius_abs - (WHEELBASE_M / 2.0)
            outer_radius = radius_abs + (WHEELBASE_M / 2.0)
            
            # Speed ratio: inner/outer = inner_radius/outer_radius
            speed_ratio = inner_radius / outer_radius if outer_radius > 0 else 0.0
            
            # Ensure minimum speed for inner wheel
            if speed_ratio < MIN_MOTOR_VALUE / motor_value:
                speed_ratio = MIN_MOTOR_VALUE / motor_value
            
            # Calculate motor values (outer wheel uses full speed, inner wheel uses ratio)
            base_left_motor = motor_value * speed_ratio * direction
            base_right_motor = motor_value * direction
        else:
            # Right turn: right wheel is inner (slower), left wheel is outer (faster)
            inner_radius = radius_abs - (WHEELBASE_M / 2.0)
            outer_radius = radius_abs + (WHEELBASE_M / 2.0)
            
            # Speed ratio: inner/outer = inner_radius/outer_radius
            speed_ratio = inner_radius / outer_radius if outer_radius > 0 else 0.0
            
            # Ensure minimum speed for inner wheel
            if speed_ratio < MIN_MOTOR_VALUE / motor_value:
                speed_ratio = MIN_MOTOR_VALUE / motor_value
            
            # Calculate motor values (outer wheel uses full speed, inner wheel uses ratio)
            base_left_motor = motor_value * direction
            base_right_motor = motor_value * speed_ratio * direction
        
        # Apply balance correction for forward movement only
        offset_to_apply = 0.0
        if direction > 0:
            # Forward movement: apply left motor offset
            offset_to_apply = LEFT_MOTOR_OFFSET
            
            # Check for overflow with left motor
            if base_left_motor + LEFT_MOTOR_OFFSET > 1.0:
                overflow = base_left_motor + LEFT_MOTOR_OFFSET - 1.0
                offset_to_apply = LEFT_MOTOR_OFFSET - overflow
        
        # Calculate final motor values with offset
        left_motor = base_left_motor + offset_to_apply
        right_motor = base_right_motor
        
        # Handle overflow by adjusting right motor
        if left_motor > 1.0:
            overflow = left_motor - 1.0
            left_motor = 1.0
            # Reduce right motor proportionally
            right_motor = max(0.0, right_motor - overflow) * direction
        elif left_motor < -1.0:
            overflow = abs(left_motor + 1.0)
            left_motor = -1.0
            right_motor = min(0.0, right_motor + overflow) * direction
        
        print(f"{PREFIX_COLOR}{PRINT_PREFIX} Moving arc: radius={radius_m:+.3f}m, angle={angle_degrees:+.1f}°, "
              f"arc_distance={arc_distance_m:.3f}m at {actual_speed_m_s:.3f} m/s "
              f"(robot_speed={motor_value:.2f}, constant={constant_duration:.2f}s, decel={deceleration_time:.2f}s){PREFIX_RESET}")
        
        # Start both motors simultaneously from static friction threshold
        left_abs = abs(left_motor)
        right_abs = abs(right_motor)
        start_left = min(STATIC_FRICTION_THRESHOLD, left_abs)
        start_right = min(STATIC_FRICTION_THRESHOLD, right_abs)
        left_dir = 1 if left_motor >= 0 else -1
        right_dir = 1 if right_motor >= 0 else -1
        
        # Start both motors at threshold simultaneously
        self.robot.left_motor.value = start_left * left_dir
        self.robot.right_motor.value = start_right * right_dir
        time.sleep(0.05)
        
        # Then set to target speed
        self.robot.left_motor.value = left_motor
        self.robot.right_motor.value = right_motor
        
        # Constant speed phase
        if constant_duration > 0:
            time.sleep(constant_duration)
        
        # Smooth deceleration phase
        self._smooth_stop(left_motor, right_motor, deceleration_time)
    
    def queue_movement(self, movements: List[Tuple[Callable, ...]]):
        """
        Queue a list of movements to be executed sequentially.
        
        Args:
            movements: List of tuples, each containing a function and its arguments.
                        Valid functions are move_distance, move_arc, and rotate.
                        Example: [(self.move_distance, 0.5), (self.rotate, 90)]
        """
        PRINT_PREFIX = "[QUEUE_MOVEMENT]"
        PREFIX_COLOR = "\033[92m"
        PREFIX_RESET = "\033[0m"
        
        valid_funcs = {self.move_distance, self.move_arc, self.rotate}
        
        for i, movement in enumerate(movements):
            if not isinstance(movement, tuple) or len(movement) == 0:
                raise ValueError(f"{PREFIX_COLOR}{PRINT_PREFIX} Invalid movement at index {i}: must be a non-empty tuple{PREFIX_RESET}")
            
            func, *args = movement
            
            if func not in valid_funcs:
                raise ValueError(f"{PREFIX_COLOR}{PRINT_PREFIX} Invalid function at index {i}: must be move_distance, move_arc, or rotate{PREFIX_RESET}")
            
            if func == self.move_distance:
                if len(args) < 1 or len(args) > 2:
                    raise ValueError(f"{PREFIX_COLOR}{PRINT_PREFIX} move_distance requires 1-2 args at index {i}{PREFIX_RESET}")
                func(*args)
            elif func == self.rotate:
                if len(args) < 1 or len(args) > 2:
                    raise ValueError(f"{PREFIX_COLOR}{PRINT_PREFIX} rotate requires 1-2 args at index {i}{PREFIX_RESET}")
                func(*args)
            elif func == self.move_arc:
                if len(args) < 2 or len(args) > 3:
                    raise ValueError(f"{PREFIX_COLOR}{PRINT_PREFIX} move_arc requires 2-3 args at index {i}{PREFIX_RESET}")
                func(*args)
            
            if i < len(movements) - 1:
                time.sleep(0.5)
    
    def stop(self):
        self.robot.stop()
        print("[STOP] Motors stopped")

if __name__ == "__main__":
    """
    Test script for RobotController movement capabilities.
    Draws a square (0.25m sides) and a full circle (0.25m radius).
    """
    print("="*60)
    print("JETBOT MOVEMENT TESTS")
    print("="*60)
    
    # Initialize robot controller
    print("\nInitializing robot controller...")
    controller = RobotController()
    print("Robot controller initialized\n")
    
    # Test 1: Draw a square with 0.25m sides
    print("="*60)
    print("TEST 1: Drawing a square (0.25m sides)")
    print("="*60)
    
    square_movements = [
        (controller.move_distance, 0.25),
        (controller.rotate, 90),
        (controller.move_distance, 0.25),
        (controller.rotate, 90),
        (controller.move_distance, 0.25),
        (controller.rotate, 90),
        (controller.move_distance, 0.25),
        (controller.rotate, 90),
    ]
    
    print("\nExecuting square movements...")
    controller.queue_movement(square_movements)
    print("\nSquare complete!")
    time.sleep(2)
    
    # Test 2: Draw a full circle with 0.25m radius
    print("\n" + "="*60)
    print("TEST 2: Drawing a circle (0.25m radius)")
    print("="*60)
    
    circle_movements = [
        (controller.move_arc, 0.25, 360),
    ]
    
    print("\nExecuting circle movement...")
    controller.queue_movement(circle_movements)
    print("\nCircle complete!")
    
    print("\n" + "="*60)
    print("ALL TESTS COMPLETE")
    print("="*60)
    
    exit()