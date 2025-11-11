"""
Main entry point for JetBot control system.
Initializes hardware components and starts API server.
WebSocket telemetry is handled by yoloe-backend on port 8001.
"""
from jetbot import Robot, Camera, UltrasonicSensor

from schemas import (
    IMAGE_WIDTH,
    IMAGE_HEIGHT,
    I2C_BUS,
    LEFT_MOTOR_CHANNEL,
    RIGHT_MOTOR_CHANNEL,
)
from controls import RobotController
from api import APIServer

def print_success(msg):
    GREEN = "\033[92m"
    RESET = "\033[0m"
    print(f"{GREEN}[SUCCESS]{RESET} {msg}")

def main():
    """Initialize hardware and start servers."""
    print("Starting JetBot control system...")
    
    # Initialize hardware components
    print("Initializing hardware components...")
    try:
        robot = Robot(
            i2c_bus=I2C_BUS,
            left_motor_channel=LEFT_MOTOR_CHANNEL,
            right_motor_channel=RIGHT_MOTOR_CHANNEL
        )
        print_success("Robot initialized")
        
        camera = Camera(width=IMAGE_WIDTH, height=IMAGE_HEIGHT)
        print_success("Camera initialized")
        
        ultrasonic = UltrasonicSensor()
        print_success("Ultrasonic sensor initialized")
        
    except Exception as e:
        print(f"ERROR: Failed to initialize hardware: {e}")
        raise
    
    # Initialize RobotController with hardware components
    try:
        robot_controller = RobotController(
            robot=robot,
            camera=camera,
            ultrasonic=ultrasonic
        )
        print_success("RobotController initialized")
    except Exception as e:
        print(f"ERROR: Failed to initialize RobotController: {e}")
        raise
    
    # Initialize API server
    try:
        api_server = APIServer(
            robot_controller=robot_controller
        )
        print("API server initialized")
    except Exception as e:
        print(f"ERROR: Failed to initialize API server: {e}")
        raise
    
    # Start the API server (this blocks)
    print("\n" + "="*50)
    print("JetBot Control System Ready!")
    print("="*50)
    print(f"API Server: http://0.0.0.0:8000")
    print(f"API Docs: http://0.0.0.0:8000/docs")
    print(f"Note: WebSocket telemetry is handled by yoloe-backend on port 8001")
    print("="*50 + "\n")
    
    try:
        api_server.run(host="0.0.0.0", port=8000, reload=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
        robot_controller.stop()
        print("Goodbye!")


if __name__ == "__main__":
    main()
