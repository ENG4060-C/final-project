# FastAPI server exposing Jetbot Functionality
import math
import threading
import time
from typing import Optional, Dict

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
        # The offset is applied as a constant throughout acceleration
        base_left_motor = left_motor_target - left_offset
        base_right_motor = right_motor_target
        
        # Get absolute values and direction signs for base values
        left_base_abs = abs(base_left_motor)
        right_abs = abs(base_right_motor)
        left_dir = 1 if base_left_motor >= 0 else -1
        right_dir = 1 if right_motor_target >= 0 else -1
        
        # Get offset direction (same as left motor direction)
        offset_dir = left_dir if base_left_motor != 0 else (1 if left_offset >= 0 else -1)
        
        # Gradually increase speed from zero to target speed
        # Use a smooth linear ramp
        for step in range(ACCEL_DECEL_STEPS):
            # Calculate progress: 0.0 (stopped) up to 1.0 (target speed)
            progress = (step + 1) / ACCEL_DECEL_STEPS
            
            # Calculate base motor values (linear ramp without offset)
            left_val = left_base_abs * progress * left_dir
            right_val = right_abs * progress * right_dir
            
            # Apply constant offset to left motor throughout acceleration
            # This ensures balance correction is maintained during acceleration
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
            
            # For very small values, start from minimum to overcome static friction
            if abs(left_val) < MIN_MOTOR_VALUE and abs(left_val) > 0:
                left_val = MIN_MOTOR_VALUE * left_dir
            if abs(right_val) < MIN_MOTOR_VALUE and abs(right_val) > 0:
                right_val = MIN_MOTOR_VALUE * right_dir
            
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
        
        print(f"Moving {distance_m:+.3f}m at {actual_speed_m_s:.3f} m/s "
              f"(robot_speed={motor_value_signed:+.2f}, duration={duration_s:.2f}s, "
              f"accel={acceleration_time:.2f}s, constant={constant_duration:.2f}s, "
              f"decel={deceleration_time:.2f}s)")
        
        # Smooth acceleration phase with constant offset applied throughout
        self._smooth_start(left_motor, right_motor, acceleration_time, left_offset=offset_to_apply)
        
        # Constant speed phase
        if constant_duration > 0:
            time.sleep(constant_duration)
        
        # Smooth deceleration phase
        self._smooth_stop(left_motor, right_motor, deceleration_time)
    
    def rotate(self, angle_degrees: float, robot_speed: float = 0.5):
        """Rotate robot in place by specified angle."""
        
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
        
        print(f"Rotating {angle_degrees:+.1f}° at {actual_speed_m_s:.3f} m/s "
              f"(robot_speed={motor_value:.2f}, constant={constant_duration:.2f}s, decel={deceleration_time:.2f}s)")
        
        # Constant speed phase (no smooth start for rotation - causes issues)
        self.robot.left_motor.value = left_motor
        self.robot.right_motor.value = right_motor
        if constant_duration > 0:
            time.sleep(constant_duration)
        
        # Smooth deceleration phase
        self._smooth_stop(left_motor, right_motor, deceleration_time)
    
    def stop(self):
        self.robot.stop()
        print("Motors stopped")