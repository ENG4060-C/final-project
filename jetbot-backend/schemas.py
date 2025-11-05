"""
Shared types, constants, and Pydantic models for JetBot control system.
"""
from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field, field_validator


# Hardware Configuration Constants
IMAGE_WIDTH = 1640
IMAGE_HEIGHT = 1232
I2C_BUS = 7
LEFT_MOTOR_CHANNEL = 1
RIGHT_MOTOR_CHANNEL = 2
MAX_MOTOR_VALUE = 1.0         
MIN_MOTOR_VALUE = 0.3
STATIC_FRICTION_THRESHOLD = 0.30
ULTRASONIC_SAFETY_THRESHOLD_M = 0.05

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

# Movement Type Enum
class MovementType(str, Enum):
    """Enum for valid movement types."""
    MOVE_DISTANCE = "move_distance"
    ROTATE = "rotate"
    MOVE_ARC = "move_arc"

# Movement Request Model
class MoveDistanceRequest(BaseModel):
    """Request model for move_distance endpoint."""
    distance_m: float = Field(
        ..., 
        description="Distance in meters (positive=forward, negative=backward)",
        ge=-10.0,
        le=10.0
    )
    robot_speed: float = Field(
        default=0.5,
        description="Motor speed value",
        ge=MIN_MOTOR_VALUE,
        le=MAX_MOTOR_VALUE
    )

    class Config:
        json_schema_extra = {
            "example": {
                "distance_m": 0.5,
                "robot_speed": 0.5
            }
        }

# Rotate Request Model
class RotateRequest(BaseModel):
    """Request model for rotate endpoint."""
    angle_degrees: float = Field(
        ...,
        description="Rotation angle in degrees (positive=CCW, negative=CW)",
        ge=-720.0,
        le=720.0
    )
    robot_speed: float = Field(
        default=0.4,
        description="Motor speed value",
        ge=MIN_MOTOR_VALUE,
        le=MAX_MOTOR_VALUE
    )

    class Config:
        json_schema_extra = {
            "example": {
                "angle_degrees": 90.0,
                "robot_speed": 0.4
            }
        }

# Move Arc Request Model
class MoveArcRequest(BaseModel):
    """Request model for move_arc endpoint."""
    radius_m: float = Field(
        ...,
        description="Turn radius in meters (positive=left, negative=right)",
        ge=-5.0,
        le=5.0
    )
    angle_degrees: float = Field(
        ...,
        description="Angle to travel along arc (positive=forward, negative=backward)",
        ge=-720.0,
        le=720.0
    )
    robot_speed: float = Field(
        default=0.5,
        description="Motor speed value",
        ge=MIN_MOTOR_VALUE,
        le=MAX_MOTOR_VALUE
    )

    @field_validator('radius_m')
    @classmethod
    def radius_not_zero(cls, v: float) -> float:
        """Ensure radius is not zero."""
        if abs(v) < 0.001:
            raise ValueError("radius_m cannot be zero")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "radius_m": 0.25,
                "angle_degrees": 360.0,
                "robot_speed": 0.5
            }
        }

# Movement Command Model
class MovementCommand(BaseModel):
    """Single movement command for queue."""
    type: MovementType = Field(..., description="Type of movement")
    distance_m: Optional[float] = Field(None, description="Distance for move_distance")
    angle_degrees: Optional[float] = Field(None, description="Angle for rotate or move_arc")
    radius_m: Optional[float] = Field(None, description="Radius for move_arc")
    robot_speed: Optional[float] = Field(None, description="Speed override (uses default if not provided)")

    @field_validator('distance_m')
    @classmethod
    def validate_distance(cls, v: Optional[float]) -> Optional[float]:
        """Validate distance is within reasonable bounds."""
        if v is not None and abs(v) > 10.0:
            raise ValueError("distance_m must be between -10.0 and 10.0 meters")
        return v

    @field_validator('angle_degrees')
    @classmethod
    def validate_angle(cls, v: Optional[float]) -> Optional[float]:
        """Validate angle is within reasonable bounds."""
        if v is not None and abs(v) > 720.0:
            raise ValueError("angle_degrees must be between -720.0 and 720.0 degrees")
        return v

    @field_validator('radius_m')
    @classmethod
    def validate_radius(cls, v: Optional[float]) -> Optional[float]:
        """Validate radius is within reasonable bounds and not zero."""
        if v is not None:
            if abs(v) > 5.0:
                raise ValueError("radius_m must be between -5.0 and 5.0 meters")
            if abs(v) < 0.001:
                raise ValueError("radius_m cannot be zero")
        return v

    @field_validator('robot_speed')
    @classmethod
    def validate_speed(cls, v: Optional[float]) -> Optional[float]:
        """Validate robot speed is within valid motor range."""
        if v is not None and (v < MIN_MOTOR_VALUE or v > MAX_MOTOR_VALUE):
            raise ValueError(f"robot_speed must be between {MIN_MOTOR_VALUE} and {MAX_MOTOR_VALUE}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "type": "move_distance",
                "distance_m": 0.5,
                "robot_speed": 0.5
            }
        }

# Queue Movement Request Model
class QueueMovementRequest(BaseModel):
    """Request model for queue_movement endpoint."""
    movements: List[MovementCommand] = Field(
        ...,
        description="List of movements to execute sequentially",
        min_length=1,
        max_length=100
    )

    class Config:
        json_schema_extra = {
            "example": {
                "movements": [
                    {"type": "move_distance", "distance_m": 0.25},
                    {"type": "rotate", "angle_degrees": 90.0},
                    {"type": "move_arc", "radius_m": 0.25, "angle_degrees": 360.0}
                ]
            }
        }


# Success Response Model
class SuccessResponse(BaseModel):
    """Standard success response."""
    success: bool = True
    message: str
    data: Optional[dict] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    robot_initialized: bool


class MovementStatus(str, Enum):
    """Enum for movement status."""
    COMPLETED = "completed"
    SAFETY = "safety"
    INVALID_MOVEMENT = "invalid_movement"


class MovementResult(BaseModel):
    """Response model for movement operations."""
    status: MovementStatus = Field(..., description="Status of the movement")
    final_ultrasonic: Optional[float] = Field(None, description="Final ultrasonic reading in meters")
    info: dict = Field(..., description="Movement parameters that were executed")

