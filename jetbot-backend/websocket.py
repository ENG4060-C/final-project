"""
WebSocket server for real-time JetBot telemetry.
Broadcasts ultrasonic sensor data, motor values, and camera images to all connected clients.
"""
import asyncio
import json
import base64
import time
from typing import Set, Optional
from fastapi import WebSocket, WebSocketDisconnect
import cv2
import numpy as np

from jetbot import Robot, Camera, UltrasonicSensor


class WebSocketServer:
    """
    WebSocket server for broadcasting robot telemetry to connected clients.
    """
    
    def __init__(self, robot: Robot, camera: Camera, ultrasonic: UltrasonicSensor):
        """
        Initialize WebSocket server with hardware components.
        
        Args:
            robot: Robot instance for motor control
            camera: Camera instance for image capture
            ultrasonic: UltrasonicSensor instance for distance measurement
        """
        self.robot = robot
        self.camera = camera
        self.ultrasonic = ultrasonic
        
        self.active_connections: Set[WebSocket] = set()
        self._broadcast_task: Optional[asyncio.Task] = None
        self._broadcast_running = False
    
    async def connect_websocket(self, websocket: WebSocket):
        """
        Handle new WebSocket connection.
        
        Args:
            websocket: WebSocket connection
        """
        await websocket.accept()
        self.active_connections.add(websocket)
        print(f"WebSocket client connected. Total clients: {len(self.active_connections)}")
        
        # Start broadcast task if not already running
        if not self._broadcast_running:
            self._broadcast_running = True
            self._broadcast_task = asyncio.create_task(self._broadcast_telemetry())
        
        try:
            # Keep connection alive and handle disconnections
            while True:
                # Wait for any message (ping/pong or disconnect)
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                    # Echo back or handle ping
                    if data == "ping":
                        await websocket.send_text("pong")
                except asyncio.TimeoutError:
                    # Timeout is fine, just continue
                    continue
        except WebSocketDisconnect:
            # Use discard() instead of remove() to avoid KeyError if already removed
            self.active_connections.discard(websocket)
            print(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")
            
            # Stop broadcast task if no clients connected
            if len(self.active_connections) == 0 and self._broadcast_task:
                self._broadcast_running = False
                self._broadcast_task.cancel()
                try:
                    await self._broadcast_task
                except asyncio.CancelledError:
                    pass
                self._broadcast_task = None
    
    async def _broadcast_telemetry(self):
        """
        Background task that continuously reads sensor data and broadcasts to all clients.
        """
        try:
            while self._broadcast_running:
                if len(self.active_connections) == 0:
                    await asyncio.sleep(0.1)
                    continue
                
                # Read sensor data
                telemetry_data = await self._read_telemetry_data()
                
                # Broadcast to all connected clients
                if telemetry_data:
                    message = json.dumps(telemetry_data)
                    disconnected_clients = set()
                    
                    for client in self.active_connections:
                        try:
                            await client.send_text(message)
                        except Exception as e:
                            # Client disconnected or error
                            print(f"Error sending to client: {e}")
                            disconnected_clients.add(client)
                    
                    # Remove disconnected clients
                    for client in disconnected_clients:
                        self.active_connections.discard(client)
                
                # Small delay to prevent overwhelming the system
                await asyncio.sleep(0.033)  # ~30 FPS for telemetry updates
                
        except asyncio.CancelledError:
            print("Broadcast task cancelled")
        except Exception as e:
            print(f"Error in broadcast task: {e}")
        finally:
            self._broadcast_running = False
    
    async def _read_telemetry_data(self):
        """
        Read all telemetry data from robot sensors.
        
        Returns:
            dict: Telemetry data with ultrasonic, motor values, and image
        """
        try:
            # Read ultrasonic sensor
            ultrasonic_distance = None
            try:
                ultrasonic_distance = self.ultrasonic.read_distance()
            except Exception as e:
                print(f"Error reading ultrasonic: {e}")
            
            # Read motor values
            left_motor_value = None
            right_motor_value = None
            try:
                left_motor_value = float(self.robot.left_motor.value)
                right_motor_value = float(self.robot.right_motor.value)
            except Exception as e:
                print(f"Error reading motor values: {e}")
            
            # Read camera image
            image_data = None
            try:
                # Get image from camera
                image = self.camera.value
                
                # Convert to numpy array if needed
                if not isinstance(image, np.ndarray):
                    image = np.array(image)
                
                # Encode image as JPEG
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]  # 85% quality
                _, encoded_image = cv2.imencode('.jpg', image, encode_param)
                
                # Convert to base64 string
                image_data = base64.b64encode(encoded_image).decode('utf-8')
            except Exception as e:
                print(f"Error reading camera: {e}")
            
            # Construct telemetry message
            telemetry = {
                "timestamp": time.time(),
                "ultrasonic": {
                    "distance_m": ultrasonic_distance,
                    "distance_cm": ultrasonic_distance * 100 if ultrasonic_distance is not None else None
                },
                "motors": {
                    "left": left_motor_value,
                    "right": right_motor_value
                },
                "image": image_data  # Base64 encoded JPEG
            }
            
            return telemetry
            
        except Exception as e:
            print(f"Error reading telemetry data: {e}")
            return None
    
    def get_active_connections_count(self):
        """Get the number of currently connected WebSocket clients."""
        return len(self.active_connections)
