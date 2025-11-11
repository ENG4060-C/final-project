"""
FastAPI server for JetBot remote control.
Provides type-safe REST API endpoints for robot movement control.
"""
from typing import Any, Optional, Dict, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Body, status
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
    MovementResult,
    MovementStatus,
)


class APIServer:
    """
    FastAPI server for JetBot control API.
    """
    
    def __init__(self, robot_controller: RobotController):
        """
        Initialize API server with robot controller.
        
        Args:
            robot_controller: RobotController instance
        """
        self.robot_controller = robot_controller
        
        # Create FastAPI app
        self.app = FastAPI(
            title="JetBot Control API",
            description="Type-safe REST API for controlling JetBot robot movements",
            version="1.0.0",
            lifespan=self._create_lifespan()
        )
        
        # Configure CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Register routes
        self._register_routes()
    
    def _create_lifespan(self):
        """Create lifespan context manager."""
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            """Initialize and cleanup."""
            print("Starting JetBot API server...")
            yield
            
            # Cleanup
            if self.robot_controller:
                print("Shutting down robot controller...")
                self.robot_controller.stop()
        
        return lifespan
    
    def _register_routes(self):
        """Register all API routes."""
        
        @self.app.get("/", response_model=HealthResponse)
        async def root():
            """Root endpoint - health check."""
            return HealthResponse(
                status="online",
                robot_initialized=self.robot_controller is not None
            )
        
        @self.app.get("/health", response_model=HealthResponse)
        async def health_check():
            """Health check endpoint."""
            return HealthResponse(
                status="healthy" if self.robot_controller is not None else "degraded",
                robot_initialized=self.robot_controller is not None
            )
        
        @self.app.post("/move/distance", response_model=MovementResult)
        async def move_distance(request: MoveDistanceRequest):
            """
            Move robot forward or backward for a specified distance.
            
            - **distance_m**: Distance in meters (+ forward, - backward)
            - **robot_speed**: Motor speed value (0.3 to 1.0)
            
            Returns movement result with status, final ultrasonic reading, and movement info.
            """
            robot = self._get_robot()
            
            try:
                result = robot.move_distance(
                    distance_m=request.distance_m,
                    robot_speed=request.robot_speed
                )
                return MovementResult(
                    status=MovementStatus(result["status"]),
                    final_ultrasonic=result["final_ultrasonic"],
                    info=result["info"]
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to execute move_distance: {str(e)}"
                )
        
        @self.app.post("/move/rotate", response_model=MovementResult)
        async def rotate(request: RotateRequest):
            """
            Rotate robot in place by specified angle.
            
            - **angle_degrees**: Rotation angle (+ CCW, - CW)
            - **robot_speed**: Motor speed value (0.3 to 1.0)
            
            Returns movement result with status, final ultrasonic reading, and movement info.
            """
            robot = self._get_robot()
            
            try:
                result = robot.rotate(
                    angle_degrees=request.angle_degrees,
                    robot_speed=request.robot_speed
                )
                return MovementResult(
                    status=MovementStatus(result["status"]),
                    final_ultrasonic=result["final_ultrasonic"],
                    info=result["info"]
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to execute rotate: {str(e)}"
                )
        
        @self.app.post("/move/arc", response_model=MovementResult)
        async def move_arc(request: MoveArcRequest):
            """
            Move robot in an arc (turning while moving).
            
            - **radius_m**: Turn radius in meters (+ left, - right)
            - **angle_degrees**: Angle to travel along arc (+ forward, - backward)
            - **robot_speed**: Motor speed value (0.3 to 1.0)
            
            Returns movement result with status, final ultrasonic reading, and movement info.
            """
            robot = self._get_robot()
            
            try:
                result = robot.move_arc(
                    radius_m=request.radius_m,
                    angle_degrees=request.angle_degrees,
                    robot_speed=request.robot_speed
                )
                return MovementResult(
                    status=MovementStatus(result["status"]),
                    final_ultrasonic=result["final_ultrasonic"],
                    info=result["info"]
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to execute move_arc: {str(e)}"
                )

        @self.app.post("/vision/labels", response_model=SuccessResponse)
        async def set_labels(request: dict):
            """
            Update YOLO-E detection labels.

            Accepts a JSON body:
            {
                "labels": ["person", "bottle", "dog"]
            }
            """
            robot = self._get_robot()

            try:
                labels = request.get("labels")
                if not isinstance(labels, list):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Field 'labels' must be a list of strings"
                    )

                await robot.set_labels(labels)

                return SuccessResponse(
                    message=f"Sent {len(labels)} labels to YOLO-E backend",
                    data={"labels": labels}
                )

            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to set labels: {str(e)}"
                )
            
        @self.app.post("/vision/scan", response_model=Dict[str, List[str]])
        async def scan(body: Optional[Any] = Body(default=None)):
            robot = self._get_robot()

            # Parse labels flexibly
            scan_labels: List[str] = []
            if isinstance(body, list):
                scan_labels = [str(x) for x in body]
            elif isinstance(body, dict) and "labels" in body:
                val = body.get("labels")
                if not isinstance(val, list):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="'labels' must be a list of strings"
                    )
                scan_labels = [str(x) for x in val]
            
            try:
                sectors = robot.scan(labels=scan_labels, step_degrees=45, idle_time=1.0)
                return sectors
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to scan: {str(e)}"
                )
            
        
        @self.app.post("/move/queue", response_model=SuccessResponse)
        async def queue_movement(request: QueueMovementRequest):
            """
            Execute a sequence of movements.
            
            Accepts a list of movement commands to be executed sequentially.
            Valid movement types: move_distance, rotate, move_arc
            """
            robot = self._get_robot()
            
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
        
        @self.app.post("/stop", response_model=SuccessResponse)
        async def stop():
            """
            Emergency stop - immediately halt all motors.
            """
            robot = self._get_robot()
            
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
    
    def _get_robot(self) -> RobotController:
        """Get robot controller instance or raise error."""
        if self.robot_controller is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Robot controller not initialized"
            )
        return self.robot_controller
    
    def run(self, host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
        """
        Run the API server.
        
        Args:
            host: Host to bind to
            port: Port to bind to
            reload: Enable auto-reload (for development)
        """
        uvicorn.run(
            self.app,
            host=host,
            port=port,
            reload=reload,
            log_level="info"
        )
