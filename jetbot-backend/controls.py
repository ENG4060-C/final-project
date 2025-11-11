# JetBot Robot Controller
import math
import time
import base64
import os
import json
import asyncio
from typing import List, Tuple, Callable, Dict, Optional
from threading import Thread
import numpy as np
import websockets

from jetbot import Robot, Camera, UltrasonicSensor
import cv2

from schemas import (
    # Hardware Configuration
    IMAGE_WIDTH,
    IMAGE_HEIGHT,
    I2C_BUS,
    LEFT_MOTOR_CHANNEL,
    RIGHT_MOTOR_CHANNEL,
    MAX_MOTOR_VALUE,
    MIN_MOTOR_VALUE,
    STATIC_FRICTION_THRESHOLD,
    ULTRASONIC_SAFETY_THRESHOLD_M,
    
    # Calibrated values
    MOTOR_SPEED_FACTOR,
    LEFT_MOTOR_OFFSET,
    WHEELBASE_M,
    ACCEL_DECEL_RATIO,
    ACCEL_DECEL_STEPS,
    MIN_ACCEL_DECEL_TIME,
    OSHOOT_CORRECTION_START,
    OSHOOT_CORRECTION_SLOPE,
    OSHOOT_CORRECTION_MAX,
)


class RobotController:
    """
    Controller for JetBot hardware providing motor and camera control.
    Includes WebSocket client for sending frames to yoloe-backend and receiving detections.
    """
    
    def __init__(self, robot: Optional[Robot] = None, camera: Optional[Camera] = None, 
                 ultrasonic: Optional[UltrasonicSensor] = None,
                 yoloe_backend_url: Optional[str] = None):
        """
        Initialize robot and camera hardware.
        
        Args:
            robot: Optional Robot instance (will be created if not provided)
            camera: Optional Camera instance (will be created if not provided)
            ultrasonic: Optional UltrasonicSensor instance (will be created if not provided)
            yoloe_backend_url: URL of yoloe-backend server (default: http://localhost:8000)
        """
        print("Initializing RobotController...")
        if robot is not None:
            self.robot = robot
        else:
            self.robot = Robot(
                i2c_bus=I2C_BUS, 
                left_motor_channel=LEFT_MOTOR_CHANNEL, 
                right_motor_channel=RIGHT_MOTOR_CHANNEL
            )
        
        if camera is not None:
            self.camera = camera
        else:
            self.camera = Camera(width=IMAGE_WIDTH, height=IMAGE_HEIGHT)
        
        if ultrasonic is not None:
            self.ultrasonic = ultrasonic
        else:
            self.ultrasonic = UltrasonicSensor()
        
        # WebSocket client for yoloe-backend
        self.yoloe_backend_url = yoloe_backend_url or "http://localhost:8002"
        self.yoloe_backend_ws_url = self.yoloe_backend_url.replace("http://", "ws://").replace("https://", "wss://")
        self.latest_detections: Optional[Dict] = None
        self._websocket_client_task: Optional[Thread] = None
        self._websocket_client_running = False
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._websocket_event_loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Start WebSocket client (handles both sending frames and receiving detections)
        self.start_websocket_client()
    
    def _check_ultrasonic_safety(self) -> Tuple[bool, Optional[float]]:
        """
        Check ultrasonic sensor for obstacles ahead.
        
        Returns:
            Tuple[bool, Optional[float]]: (is_safe, distance)
                - is_safe: True if safe to continue (> threshold), False if obstacle detected
                - distance: Distance reading in meters, or None if error/no reading
        """
        try:
            distance = self.ultrasonic.read_distance()
            if distance is not None and distance < ULTRASONIC_SAFETY_THRESHOLD_M:
                print(f"\033[91m[SAFETY] Obstacle detected at {distance:.1f}m - EMERGENCY STOP\033[0m")
                self.robot.stop()
                return False, distance
            return True, distance
        except Exception as e:
            # If sensor fails, log warning but don't halt (fail-safe behavior)
            print(f"\033[93m[SAFETY] Ultrasonic sensor error: {e}\033[0m")
            return True, None
    
    def _smooth_stop(self, left_motor_start: float, right_motor_start: float, 
                     deceleration_time: float, check_safety: bool = False):
        """
        Gradually reduce motor speed to zero over the deceleration period.
        
        Args:
            left_motor_start: Initial left motor value
            right_motor_start: Initial right motor value
            deceleration_time: Time in seconds for deceleration
            check_safety: If True, check ultrasonic sensor during deceleration (default: False)
        
        Returns:
            Tuple[bool, Optional[float]]: (success, distance)
                - success: True if deceleration completed, False if stopped due to safety check
                - distance: Distance reading in meters if stopped early, None otherwise
        """
        if deceleration_time <= 0:
            self.robot.stop()
            return True, None
        
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
            # Check safety during deceleration if requested
            check_start_time = time.time()
            if check_safety:
                is_safe, distance = self._check_ultrasonic_safety()
                if not is_safe:
                    return False, distance  # Emergency stop triggered
            check_elapsed = time.time() - check_start_time
            
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
            
            # Calculate remaining time for this step (only accounting for ultrasonic check time)
            remaining_step_time = step_time - check_elapsed
            if remaining_step_time > 0:
                time.sleep(remaining_step_time)
        
        # Final stop to ensure motors are completely off
        self.robot.stop()
        return True, None
    
    def _smooth_start(self, left_motor_target: float, right_motor_target: float, 
                     acceleration_time: float, left_offset: float = 0.0, check_safety: bool = False):
        """
        Gradually increase motor speed from zero to target speed over the acceleration period.
        
        Args:
            left_motor_target: Target left motor value
            right_motor_target: Target right motor value
            acceleration_time: Time in seconds for acceleration
            left_offset: Constant offset to apply to left motor during acceleration (default: 0.0)
                        This offset is applied as a constant value throughout acceleration, not proportional.
            check_safety: If True, check ultrasonic sensor during acceleration (default: False)
        
        Returns:
            bool: True if acceleration completed, False if stopped due to safety check
        """
        if acceleration_time <= 0:
            self.robot.left_motor.value = left_motor_target
            self.robot.right_motor.value = right_motor_target
            return True
        
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
        
        # Gradually increase speed from static friction threshold to target speed while checking safety
        for step in range(ACCEL_DECEL_STEPS):
            # Check safety during acceleration if requested
            check_start_time = time.time()
            if check_safety:
                is_safe, _ = self._check_ultrasonic_safety()
                if not is_safe:
                    return False  # Emergency stop triggered
            check_elapsed = time.time() - check_start_time
            
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
            
            # Calculate remaining time for this step (only accounting for ultrasonic check time)
            remaining_step_time = step_time - check_elapsed
            if remaining_step_time > 0:
                time.sleep(remaining_step_time)
        
        # Final set to ensure we reach exact target values
        self.robot.left_motor.value = left_motor_target
        self.robot.right_motor.value = right_motor_target
        return True
    
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
        
        # Validate inputs
        if distance_m == 0:
            final_distance = self.ultrasonic.read_distance()
            return {
                "status": "invalid_movement",
                "final_ultrasonic": final_distance,
                "info": {
                    "distance_m": distance_m,
                    "robot_speed": robot_speed,
                    "direction": 1 if distance_m >= 0 else -1
                }
            }
        
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
        
        # Ultrasonic safety check for forward movement (before starting)
        if direction > 0:
            is_safe, _ = self._check_ultrasonic_safety()
            if not is_safe:
                final_distance = self.ultrasonic.read_distance()
                return {
                    "status": "safety",
                    "final_ultrasonic": final_distance,
                    "info": {
                        "distance_m": distance_m,
                        "robot_speed": robot_speed,
                        "direction": direction
                    }
                }
        
        # Smooth acceleration phase with constant offset applied throughout
        acceleration_complete = self._smooth_start(
            left_motor, right_motor, acceleration_time, 
            left_offset=offset_to_apply, 
            check_safety=(direction > 0)
        )
        
        # If acceleration was stopped due to safety check, abort movement
        if not acceleration_complete:
            final_distance = self.ultrasonic.read_distance()
            return {
                "status": "safety",
                "final_ultrasonic": final_distance,
                "info": {
                    "distance_m": distance_m,
                    "robot_speed": robot_speed,
                    "direction": direction
                }
            }
        
        # Constant speed phase with periodic safety checks
        if constant_duration > 0:
            if direction > 0:
                # Forward movement - check safety periodically
                # Use wall-clock time to account for time spent in safety checks
                check_interval = 0.05  # Check every 50ms
                start_time = time.time()
                while True:
                    is_safe, _ = self._check_ultrasonic_safety()
                    if not is_safe:
                        final_distance = self.ultrasonic.read_distance()
                        return {
                            "status": "safety",
                            "final_ultrasonic": final_distance,
                            "info": {
                                "distance_m": distance_m,
                                "robot_speed": robot_speed,
                                "direction": direction
                            }
                        }
                    
                    # Calculate actual elapsed time (includes check duration)
                    elapsed = time.time() - start_time
                    if elapsed >= constant_duration:
                        break
                    
                    # Sleep for remaining time until next check or end of phase
                    remaining = constant_duration - elapsed
                    sleep_time = min(check_interval, remaining)
                    if sleep_time > 0:
                        time.sleep(sleep_time)
            else:
                # Backward movement - no safety check
                time.sleep(constant_duration)
        
        # Smooth deceleration phase with safety checks for forward movement
        decel_complete, decel_distance = self._smooth_stop(left_motor, right_motor, deceleration_time, check_safety=(direction > 0))
        if not decel_complete:
            return {
                "status": "safety",
                "final_ultrasonic": decel_distance,
                "info": {
                    "distance_m": distance_m,
                    "robot_speed": robot_speed,
                    "direction": direction
                }
            }
        
        # Movement completed successfully
        final_distance = self.ultrasonic.read_distance()
        return {
            "status": "completed",
            "final_ultrasonic": final_distance,
            "info": {
                "distance_m": distance_m,
                "robot_speed": robot_speed,
                "direction": direction
            }
        }
    
    def rotate(self, angle_degrees: float, robot_speed: float = 0.4):
        """Rotate robot in place by specified angle."""
        PRINT_PREFIX = "[ROTATE]"
        PREFIX_COLOR = "\033[95m"
        PREFIX_RESET = "\033[0m"
        
        # Validate inputs
        if angle_degrees == 0:
            final_distance = self.ultrasonic.read_distance()
            return {
                "status": "invalid_movement",
                "final_ultrasonic": final_distance,
                "info": {
                    "angle_degrees": angle_degrees,
                    "robot_speed": robot_speed
                }
            }
        
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
        
        # Smooth deceleration phase (no safety check for rotation)
        decel_complete, _ = self._smooth_stop(left_motor, right_motor, deceleration_time, check_safety=False)
        
        # Rotation completed successfully
        final_distance = self.ultrasonic.read_distance()
        return {
            "status": "completed",
            "final_ultrasonic": final_distance,
            "info": {
                "angle_degrees": angle_degrees,
                "robot_speed": robot_speed
            }
        }
    
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
        
        # Validate inputs
        if angle_degrees == 0 or radius_m == 0:
            final_distance = self.ultrasonic.read_distance()
            return {
                "status": "invalid_movement",
                "final_ultrasonic": final_distance,
                "info": {
                    "radius_m": radius_m,
                    "angle_degrees": angle_degrees,
                    "robot_speed": robot_speed
                }
            }
        
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
        
        # Ultrasonic safety check for forward movement (before starting)
        if direction > 0:
            is_safe, _ = self._check_ultrasonic_safety()
            if not is_safe:
                final_distance = self.ultrasonic.read_distance()
                return {
                    "status": "safety",
                    "final_ultrasonic": final_distance,
                    "info": {
                        "radius_m": radius_m,
                        "angle_degrees": angle_degrees,
                        "robot_speed": robot_speed
                    }
                }
        
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
        
        # Check safety immediately after starting motors (for forward movement)
        if direction > 0:
            is_safe, _ = self._check_ultrasonic_safety()
            if not is_safe:
                final_distance = self.ultrasonic.read_distance()
                return {
                    "status": "safety",
                    "final_ultrasonic": final_distance,
                    "info": {
                        "radius_m": radius_m,
                        "angle_degrees": angle_degrees,
                        "robot_speed": robot_speed
                    }
                }
        
        time.sleep(0.05)
        
        # Check safety again before reaching full speed (for forward movement)
        if direction > 0:
            is_safe, _ = self._check_ultrasonic_safety()
            if not is_safe:
                final_distance = self.ultrasonic.read_distance()
                return {
                    "status": "safety",
                    "final_ultrasonic": final_distance,
                    "info": {
                        "radius_m": radius_m,
                        "angle_degrees": angle_degrees,
                        "robot_speed": robot_speed
                    }
                }
        
        # Then set to target speed
        self.robot.left_motor.value = left_motor
        self.robot.right_motor.value = right_motor
        
        # Check safety after reaching target speed (for forward movement)
        if direction > 0:
            is_safe, _ = self._check_ultrasonic_safety()
            if not is_safe:
                final_distance = self.ultrasonic.read_distance()
                return {
                    "status": "safety",
                    "final_ultrasonic": final_distance,
                    "info": {
                        "radius_m": radius_m,
                        "angle_degrees": angle_degrees,
                        "robot_speed": robot_speed
                    }
                }
        
        # Constant speed phase with periodic safety checks
        if constant_duration > 0:
            if direction > 0:
                # Forward movement - check safety periodically
                # Use wall-clock time to account for time spent in safety checks
                check_interval = 0.05  # Check every 50ms
                start_time = time.time()
                while True:
                    # Check safety (this takes time, which is accounted for in elapsed)
                    is_safe, _ = self._check_ultrasonic_safety()
                    if not is_safe:
                        final_distance = self.ultrasonic.read_distance()
                        return {
                            "status": "safety",
                            "final_ultrasonic": final_distance,
                            "info": {
                                "radius_m": radius_m,
                                "angle_degrees": angle_degrees,
                                "robot_speed": robot_speed
                            }
                        }
                    
                    # Calculate actual elapsed time (includes check duration)
                    elapsed = time.time() - start_time
                    if elapsed >= constant_duration:
                        break
                    
                    # Sleep for remaining time until next check or end of phase
                    remaining = constant_duration - elapsed
                    sleep_time = min(check_interval, remaining)
                    if sleep_time > 0:
                        time.sleep(sleep_time)
            else:
                # Backward movement - no safety check
                time.sleep(constant_duration)
        
        # Smooth deceleration phase with safety checks for forward movement
        decel_complete, decel_distance = self._smooth_stop(left_motor, right_motor, deceleration_time, check_safety=(direction > 0))
        if not decel_complete:
            return {
                "status": "safety",
                "final_ultrasonic": decel_distance,
                "info": {
                    "radius_m": radius_m,
                    "angle_degrees": angle_degrees,
                    "robot_speed": robot_speed
                }
            }
        
        # Movement completed successfully
        final_distance = self.ultrasonic.read_distance()
        return {
            "status": "completed",
            "final_ultrasonic": final_distance,
            "info": {
                "radius_m": radius_m,
                "angle_degrees": angle_degrees,
                "robot_speed": robot_speed
            }
        }
    
    async def set_labels(self, labels: List[str]):
        """
        Overwrite YOLO-E labels on the backend
        
        Args:
            labels: List of strings, each representing a label.
        """
        # Validation
        if not isinstance(labels, list):
            raise ValueError("labels must be provided as a list")
        
        if self._websocket is None:
            raise RuntimeError("WebSocket connection is not active")

        payload = {
            "type": "set_labels",
            "labels": [str(x) for x in labels]
        }

        # Send payload 
        try:
            await self._websocket.send(json.dumps(payload))
            print(f"[SET_LABELS] Sent {len(labels)} labels")
        except Exception as e:
            raise RuntimeError(f"Failed to send set_labels message: {e}")
    
    def rotate_until_object_center(self, items: List[str], robot_speed: float = 0.3, center_threshold: float = 200.0):
        """
        Rotate the robot until the object is centered in the camera, or until 360 degrees is reached.
        
        Args:
            items: List of item labels to search for.
            robot_speed: Motor speed value 0.0 to 1.0 (default: 0.3)
            center_threshold: Maximum distance from image center to consider "centered" in pixels (default: 100.0)
            
        Returns:
            status dictionary of shape:
            {
                status: "found" or "not_found"
                final_ultrasonic: float
                info: {
                    items: List[str]
                    angle_degrees_found: float
                }
            }
        """
        PRINT_PREFIX = "[ROTATE_UNTIL_OBJECT_CENTER]"
        PREFIX_COLOR = "\033[96m"
        PREFIX_RESET = "\033[0m"
        
        if not items:
            raise ValueError("No items provided")
        
        # Set labels for detection
        try:
            try:
                # Try to get the current event loop
                loop = asyncio.get_running_loop()
                # We're in an async context, use the websocket event loop
                if self._websocket_event_loop is not None:
                    future = asyncio.run_coroutine_threadsafe(
                        self.set_labels(items),
                        self._websocket_event_loop
                    )
                    future.result(timeout=2.0)
                else:
                    # No websocket event loop, but we're in async context - can't use asyncio.run()
                    # Schedule on current loop instead
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, self.set_labels(items))
                        future.result(timeout=2.0)
            except RuntimeError:
                # No event loop running, safe to use asyncio.run()
                asyncio.run(self.set_labels(items))
                
        except Exception as e:
            print(f"{PREFIX_COLOR}{PRINT_PREFIX} Failed to set labels: {e}{PREFIX_RESET}")
            return {
                "status": "not_found",
                "final_ultrasonic": self.ultrasonic.read_distance(),
                "info": {
                    "items": items,
                    "angle_degrees_found": 0.0,
                }
            }
        
        # Small delay to allow labels to propagate
        time.sleep(0.5)
        
        # Check if latest_detections is available
        if self.latest_detections is None:
            return {
                "status": "not_found",
                "final_ultrasonic": self.ultrasonic.read_distance(),
                "info": {
                    "items": items,
                    "angle_degrees_found": 0.0,
                }
            }
        
        # Image center X coordinate (only check left/right, not up/down)
        image_center_x = IMAGE_WIDTH / 2.0
        
        # Clamp motor speed to valid range
        motor_value = max(MIN_MOTOR_VALUE, min(abs(robot_speed), MAX_MOTOR_VALUE))
        
        # Calculate rotation parameters for 15-degree increments
        # Use the same calculation as rotate() function
        increment_degrees = 15.0
        angle_rad = math.radians(increment_degrees)
        wheel_distance_m = angle_rad * WHEELBASE_M / 2.0
        actual_speed_m_s = motor_value * MOTOR_SPEED_FACTOR
        increment_duration_s = wheel_distance_m / actual_speed_m_s
        
        # Set motor values for CCW rotation (positive angle)
        left_motor = motor_value
        right_motor = -motor_value
        
        print(f"{PREFIX_COLOR}{PRINT_PREFIX} Searching for {items} - rotating in {increment_degrees}° increments "
              f"(pause: 0.5s after each increment, X threshold: {center_threshold}px){PREFIX_RESET}")
        
        total_angle_rotated = 0.0
        max_rotation = 360.0
        num_increments = int(max_rotation / increment_degrees) * 2 
        
        for i in range(num_increments):
            # Rotate by increment
            self.robot.left_motor.value = left_motor
            self.robot.right_motor.value = right_motor
            time.sleep(increment_duration_s)
            self.robot.stop()
            
            total_angle_rotated += increment_degrees
            
            # Wait 0.5 seconds for blur to fade (reduced from 1.0s)
            time.sleep(0.5)
            
            # Check latest detections for centered objects
            if self.latest_detections is None:
                continue
                
            detections = self.latest_detections.get("detections", [])
            
            # Check each detection to see if it matches our items and is centered horizontally
            for detection in detections:
                class_name = detection.get("class_name", "")
                
                # Check if this detection matches any of our target items
                if class_name not in items:
                    continue
                
                # Get bounding box
                box = detection.get("box", {})
                x1 = box.get("x1", 0)
                x2 = box.get("x2", 0)
                
                # Calculate center X of bounding box (ignore Y)
                box_center_x = (x1 + x2) / 2.0
                
                # Calculate horizontal distance from image center (only X, not Y)
                distance_from_center_x = abs(box_center_x - image_center_x)
                
                # Check if object is centered horizontally
                if distance_from_center_x <= center_threshold:
                    print(f"{PREFIX_COLOR}{PRINT_PREFIX} Found '{class_name}' centered at {total_angle_rotated:.1f}° "
                          f"(X distance from center: {distance_from_center_x:.1f}px){PREFIX_RESET}")
                    return {
                        "status": "found",
                        "final_ultrasonic": self.ultrasonic.read_distance(),
                        "info": {
                            "items": items,
                            "angle_degrees_found": total_angle_rotated,
                            "found_item": class_name,
                            "distance_from_center_px": distance_from_center_x
                        }
                    }
        
        # Completed full rotation without finding centered object
        print(f"{PREFIX_COLOR}{PRINT_PREFIX} Completed {total_angle_rotated:.1f}° rotation - object not centered{PREFIX_RESET}")
        return {
            "status": "not_found",
            "final_ultrasonic": self.ultrasonic.read_distance(),
            "info": {
                "items": items,
                "angle_degrees_found": total_angle_rotated,
            }
        }
    
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
        """Stop motors and WebSocket client."""
        self.robot.stop()
        self.stop_websocket_client()
        print("[STOP] Motors stopped")
    
    def start_websocket_client(self):
        """Start WebSocket client to receive detection updates from yoloe-backend."""
        if self._websocket_client_running:
            return
        
        self._websocket_client_running = True
        self._websocket_client_task = Thread(target=self._websocket_client_loop, daemon=True)
        self._websocket_client_task.start()
        print(f"[WEBSOCKET_CLIENT] Started connecting to {self.yoloe_backend_ws_url}")
    
    def stop_websocket_client(self):
        """Stop WebSocket client thread."""
        self._websocket_client_running = False
        if self._websocket_client_task:
            self._websocket_client_task.join(timeout=2.0)
        print("[WEBSOCKET_CLIENT] Stopped")
    
    def _websocket_client_loop(self):
        """Background loop that connects to yoloe-backend WebSocket and receives detection updates."""
        ws_url = f"{self.yoloe_backend_ws_url}/ws/telemetry?client=jetbot"
        
        while self._websocket_client_running:
            try:
                # Run async WebSocket client in a new event loop
                asyncio.run(self._websocket_client_async(ws_url))
            except Exception as e:
                if self._websocket_client_running:
                    print(f"[WEBSOCKET_CLIENT] Connection error: {e}, retrying in 5 seconds...")
                    time.sleep(5)
    
    async def _websocket_client_async(self, ws_url: str):
        """Async WebSocket client that sends frames and receives detection updates."""
        try:
            async with websockets.connect(ws_url) as websocket:
                # Store websocket connection as global object
                self._websocket = websocket
                self._websocket_event_loop = asyncio.get_event_loop()
                print(f"[WEBSOCKET_CLIENT] Connected to {ws_url}")
                
                # Start frame sender task
                frame_sender_task = asyncio.create_task(self._send_frames_async(websocket))
                
                try:
                    async for message in websocket:
                        if not self._websocket_client_running:
                            break
                        
                        try:
                            data = json.loads(message)
                            
                            # Update latest detections from WebSocket message
                            if data.get("type") == "detections":
                                self.latest_detections = {
                                    "detections": data.get("detections", []),
                                    "num_detections": data.get("num_detections", 0),
                                    "model": data.get("model", {}),
                                    "labels": data.get("labels", [])
                                }
                            
                            # Handle event messages (e.g., label updates)
                            elif data.get("type") == "event" and data.get("event_type") == "labels_updated":
                                labels = data.get("data", {}).get("labels", [])
                                print(f"[WEBSOCKET_CLIENT] Labels updated: {len(labels)} labels")
                            
                            # Handle label responses
                            elif data.get("type") == "labels_response":
                                print(f"[WEBSOCKET_CLIENT] Labels response received")
                        
                        except json.JSONDecodeError as e:
                            print(f"[WEBSOCKET_CLIENT] Error parsing message: {e}")
                        except Exception as e:
                            print(f"[WEBSOCKET_CLIENT] Error processing message: {e}")
                
                finally:
                    # Cancel frame sender task
                    frame_sender_task.cancel()
                    try:
                        await frame_sender_task
                    except asyncio.CancelledError:
                        pass
                    
                    # Clear websocket reference when connection closes
                    self._websocket = None
                    self._websocket_event_loop = None
        
        except websockets.exceptions.ConnectionClosed:
            if self._websocket_client_running:
                print("[WEBSOCKET_CLIENT] Connection closed, will retry...")
            self._websocket = None
            self._websocket_event_loop = None
        except Exception as e:
            if self._websocket_client_running:
                raise
            self._websocket = None
            self._websocket_event_loop = None
    
    async def _send_frames_async(self, websocket):
        """Async task that sends frames to yoloe-backend via WebSocket."""
        frame_interval = 1.0 / 30.0  # ~30 FPS
        
        while self._websocket_client_running:
            try:
                # Read camera image
                image = self.camera.value
                
                # Convert to numpy array if needed
                if not isinstance(image, np.ndarray):
                    image = np.array(image)
                
                # Encode image as JPEG
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]  # 85% quality
                _, encoded_image = cv2.imencode('.jpg', image, encode_param)
                image_b64 = base64.b64encode(encoded_image).decode('utf-8')
                
                # Read telemetry data
                ultrasonic_distance = None
                try:
                    ultrasonic_distance = self.ultrasonic.read_distance()
                except Exception as e:
                    pass  # Silent fail, will send None
                
                left_motor_value = None
                right_motor_value = None
                try:
                    left_motor_value = float(self.robot.left_motor.value)
                    right_motor_value = float(self.robot.right_motor.value)
                except Exception as e:
                    pass  # Silent fail, will send None
                
                # Prepare WebSocket message
                frame_message = {
                    "type": "frame",
                    "image": image_b64,
                    "ultrasonic": {
                        "distance_m": ultrasonic_distance,
                        "distance_cm": ultrasonic_distance * 100 if ultrasonic_distance is not None else None
                    },
                    "motors": {
                        "left": left_motor_value,
                        "right": right_motor_value
                    }
                }
                
                # Send via WebSocket
                await websocket.send(json.dumps(frame_message))
                
                # Sleep to maintain frame rate
                await asyncio.sleep(frame_interval)
                
            except Exception as e:
                if self._websocket_client_running:
                    print(f"[WEBSOCKET_CLIENT] Error sending frame: {e}")
                await asyncio.sleep(frame_interval)
                
    def get_latest_detections(self) -> Optional[Dict]:
        """
        Get the latest detection results from yoloe-backend.
        
        Returns:
            dict: Latest detection results with 'detections', 'num_detections', etc.
                  Returns None if no detections available yet.
        """
        return self.latest_detections

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