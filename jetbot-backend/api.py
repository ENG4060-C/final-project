"""
FastAPI server for JetBot remote control.
Provides type-safe REST API endpoints for robot movement control.
"""
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from controls import RobotController
from schemas import (
    MovementType,
    MoveDistanceRequest,
    RotateRequest,
    MoveArcRequest,
    MovementCommand,
    QueueMovementRequest,
    SuccessResponse,
    HealthResponse,
)

# Global robot controller instance
robot_controller: Optional[RobotController] = None

# Lifespan Function to Initialize and Cleanup Robot Controller
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup robot controller."""
    global robot_controller
    print("Starting JetBot API server...")
    try:
        robot_controller = RobotController()
        print("Robot controller initialized successfully")
    except Exception as e:
        print(f"ERROR: Failed to initialize robot controller: {e}")
        robot_controller = None
    
    yield
    
    # Cleanup
    if robot_controller:
        print("Shutting down robot controller...")
        robot_controller.stop()

# FastAPI Application Setup
app = FastAPI(
    title="JetBot Control API",
    description="Type-safe REST API for controlling JetBot robot movements",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper Function to Get Robot Controller or raise error
def get_robot() -> RobotController:
    """Get robot controller instance or raise error."""
    if robot_controller is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Robot controller not initialized"
        )
    return robot_controller


# API Check Endpoint
@app.get("/", response_model=HealthResponse)
async def root():
    """Root endpoint - health check."""
    return HealthResponse(
        status="online",
        robot_initialized=robot_controller is not None
    )

# Health Check Endpoint
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy" if robot_controller is not None else "degraded",
        robot_initialized=robot_controller is not None
    )

# Move Distance Endpoint
@app.post("/move/distance", response_model=SuccessResponse)
async def move_distance(request: MoveDistanceRequest):
    """
    Move robot forward or backward for a specified distance.
    
    - **distance_m**: Distance in meters (+ forward, - backward)
    - **robot_speed**: Motor speed value (0.3 to 1.0)
    """
    robot = get_robot()
    
    try:
        robot.move_distance(
            distance_m=request.distance_m,
            robot_speed=request.robot_speed
        )
        return SuccessResponse(
            message=f"Moved {request.distance_m:+.3f}m at speed {request.robot_speed:.2f}",
            data={
                "distance_m": request.distance_m,
                "robot_speed": request.robot_speed
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute move_distance: {str(e)}"
        )

# Rotate Endpoint
@app.post("/move/rotate", response_model=SuccessResponse)
async def rotate(request: RotateRequest):
    """
    Rotate robot in place by specified angle.
    
    - **angle_degrees**: Rotation angle (+ CCW, - CW)
    - **robot_speed**: Motor speed value (0.3 to 1.0)
    """
    robot = get_robot()
    
    try:
        robot.rotate(
            angle_degrees=request.angle_degrees,
            robot_speed=request.robot_speed
        )
        return SuccessResponse(
            message=f"Rotated {request.angle_degrees:+.1f}° at speed {request.robot_speed:.2f}",
            data={
                "angle_degrees": request.angle_degrees,
                "robot_speed": request.robot_speed
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute rotate: {str(e)}"
        )

# Move Arc Endpoint
@app.post("/move/arc", response_model=SuccessResponse)
async def move_arc(request: MoveArcRequest):
    """
    Move robot in an arc (turning while moving).
    
    - **radius_m**: Turn radius in meters (+ left, - right)
    - **angle_degrees**: Angle to travel along arc (+ forward, - backward)
    - **robot_speed**: Motor speed value (0.3 to 1.0)
    """
    robot = get_robot()
    
    try:
        robot.move_arc(
            radius_m=request.radius_m,
            angle_degrees=request.angle_degrees,
            robot_speed=request.robot_speed
        )
        return SuccessResponse(
            message=f"Arc: radius={request.radius_m:+.3f}m, angle={request.angle_degrees:+.1f}° at speed {request.robot_speed:.2f}",
            data={
                "radius_m": request.radius_m,
                "angle_degrees": request.angle_degrees,
                "robot_speed": request.robot_speed
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute move_arc: {str(e)}"
        )

# Queue Movement Endpoint
@app.post("/move/queue", response_model=SuccessResponse)
async def queue_movement(request: QueueMovementRequest):
    """
    Execute a sequence of movements.
    
    Accepts a list of movement commands to be executed sequentially.
    Valid movement types: move_distance, rotate, move_arc
    """
    robot = get_robot()
    
    try:
        # Convert API movements to controller format
        movements = []
        
        for i, cmd in enumerate(request.movements):
            if cmd.type == MovementType.MOVE_DISTANCE:
                if cmd.distance_m is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Movement {i}: move_distance requires distance_m"
                    )
                if cmd.robot_speed is not None:
                    movements.append((robot.move_distance, cmd.distance_m, cmd.robot_speed))
                else:
                    movements.append((robot.move_distance, cmd.distance_m))
            
            elif cmd.type == MovementType.ROTATE:
                if cmd.angle_degrees is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Movement {i}: rotate requires angle_degrees"
                    )
                if cmd.robot_speed is not None:
                    movements.append((robot.rotate, cmd.angle_degrees, cmd.robot_speed))
                else:
                    movements.append((robot.rotate, cmd.angle_degrees))
            
            elif cmd.type == MovementType.MOVE_ARC:
                if cmd.radius_m is None or cmd.angle_degrees is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Movement {i}: move_arc requires radius_m and angle_degrees"
                    )
                if cmd.robot_speed is not None:
                    movements.append((robot.move_arc, cmd.radius_m, cmd.angle_degrees, cmd.robot_speed))
                else:
                    movements.append((robot.move_arc, cmd.radius_m, cmd.angle_degrees))
        
        # Execute movement queue
        robot.queue_movement(movements)
        
        return SuccessResponse(
            message=f"Successfully executed {len(movements)} movements",
            data={
                "movement_count": len(movements),
                "movements": [cmd.dict() for cmd in request.movements]
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute movement queue: {str(e)}"
        )

# Stop Endpoint
@app.post("/stop", response_model=SuccessResponse)
async def stop():
    """
    Emergency stop - immediately halt all motors.
    """
    robot = get_robot()
    
    try:
        robot.stop()
        return SuccessResponse(
            message="Robot stopped"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop robot: {str(e)}"
        )

if __name__ == "__main__":
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )

