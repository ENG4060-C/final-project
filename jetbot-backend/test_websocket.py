"""
Test script for WebSocket telemetry feed.
Connects to the WebSocket server and displays ultrasonic/motor data and camera feed.
"""
import asyncio
import json
import base64
import cv2
import numpy as np
import os
from websockets import connect


# Check if display is available
DISPLAY_AVAILABLE = os.environ.get('DISPLAY') is not None
try:
    # Try to create a test window to check if display works
    test_img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.namedWindow("test", cv2.WINDOW_NORMAL)
    cv2.destroyWindow("test")
    DISPLAY_AVAILABLE = True
except:
    DISPLAY_AVAILABLE = False


async def test_websocket():
    """Connect to WebSocket and display telemetry data."""
    uri = "ws://localhost:8000/ws/telemetry"
    
    print("Connecting to WebSocket server...")
    print(f"URI: {uri}")
    if not DISPLAY_AVAILABLE:
        print("⚠ Display not available - images will be saved to 'websocket_frames/' directory")
        os.makedirs("websocket_frames", exist_ok=True)
    print("Press Ctrl+C to exit\n")
    
    try:
        async with connect(uri) as websocket:
            print("✓ Connected to WebSocket server\n")
            
            frame_count = 0
            
            async for message in websocket:
                try:
                    # Parse JSON message
                    data = json.loads(message)
                    
                    # Extract telemetry data
                    timestamp = data.get("timestamp", 0)
                    ultrasonic = data.get("ultrasonic", {})
                    motors = data.get("motors", {})
                    image_data = data.get("image")
                    
                    # Print ultrasonic data
                    distance_m = ultrasonic.get("distance_m")
                    distance_cm = ultrasonic.get("distance_cm")
                    if distance_m is not None:
                        print(f"\r[Ultrasonic] Distance: {distance_m:.3f}m ({distance_cm:.1f}cm)", end="", flush=True)
                    else:
                        print(f"\r[Ultrasonic] Distance: N/A", end="", flush=True)
                    
                    # Print motor values
                    left_motor = motors.get("left")
                    right_motor = motors.get("right")
                    if left_motor is not None and right_motor is not None:
                        print(f" | [Motors] Left: {left_motor:+.3f}, Right: {right_motor:+.3f}", end="", flush=True)
                    else:
                        print(f" | [Motors] N/A", end="", flush=True)
                    
                    # Decode and display/save image
                    if image_data:
                        try:
                            # Decode base64 image
                            image_bytes = base64.b64decode(image_data)
                            
                            # Convert bytes to numpy array
                            nparr = np.frombuffer(image_bytes, np.uint8)
                            
                            # Decode JPEG image
                            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            
                            if image is not None:
                                frame_count += 1
                                
                                # Add text overlay with telemetry info
                                overlay = image.copy()
                                
                                # Draw semi-transparent rectangle for text
                                cv2.rectangle(overlay, (10, 10), (400, 120), (0, 0, 0), -1)
                                image = cv2.addWeighted(overlay, 0.6, image, 0.4, 0)
                                
                                # Add text
                                font = cv2.FONT_HERSHEY_SIMPLEX
                                y_offset = 30
                                line_height = 25
                                
                                if distance_m is not None:
                                    cv2.putText(image, f"Distance: {distance_m:.3f}m ({distance_cm:.1f}cm)", 
                                              (20, y_offset), font, 0.6, (0, 255, 0), 2)
                                else:
                                    cv2.putText(image, "Distance: N/A", 
                                              (20, y_offset), font, 0.6, (128, 128, 128), 2)
                                
                                y_offset += line_height
                                if left_motor is not None and right_motor is not None:
                                    cv2.putText(image, f"Motors: L={left_motor:+.3f} R={right_motor:+.3f}", 
                                              (20, y_offset), font, 0.6, (0, 255, 0), 2)
                                else:
                                    cv2.putText(image, "Motors: N/A", 
                                              (20, y_offset), font, 0.6, (128, 128, 128), 2)
                                
                                y_offset += line_height
                                cv2.putText(image, f"Frame: {frame_count}", 
                                          (20, y_offset), font, 0.6, (255, 255, 255), 2)
                                
                                # Display or save image
                                if DISPLAY_AVAILABLE:
                                    cv2.imshow("JetBot Camera Feed", image)
                                    
                                    # Check for 'q' key press to exit
                                    if cv2.waitKey(1) & 0xFF == ord('q'):
                                        print("\n\nExiting...")
                                        break
                                else:
                                    # Save to file instead
                                    if frame_count % 10 == 0:  # Save every 10th frame to avoid disk spam
                                        filename = f"websocket_frames/frame_{frame_count:06d}.jpg"
                                        cv2.imwrite(filename, image)
                                        print(f" | [Image] Saved {filename}", end="", flush=True)
                                
                        except Exception as e:
                            print(f"\nError processing image: {e}")
                
                except json.JSONDecodeError as e:
                    print(f"\nError parsing JSON: {e}")
                except Exception as e:
                    print(f"\nError processing message: {e}")
    
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\nConnection error: {e}")
    finally:
        if DISPLAY_AVAILABLE:
            cv2.destroyAllWindows()
        print("\nDisconnected from WebSocket server")
        if not DISPLAY_AVAILABLE and frame_count > 0:
            print(f"Saved {frame_count // 10} frames to 'websocket_frames/' directory")


if __name__ == "__main__":
    print("="*60)
    print("JetBot WebSocket Telemetry Test")
    print("="*60)
    print("\nThis script will:")
    print("  1. Connect to ws://localhost:8000/ws/telemetry")
    print("  2. Print ultrasonic and motor values to terminal")
    if DISPLAY_AVAILABLE:
        print("  3. Display camera feed in a popup window")
        print("\nPress 'q' in the image window to exit")
    else:
        print("  3. Save camera frames to 'websocket_frames/' directory")
        print("\nPress Ctrl+C to exit")
    print("="*60 + "\n")
    
    try:
        asyncio.run(test_websocket())
    except KeyboardInterrupt:
        print("\n\nExiting...")
        cv2.destroyAllWindows()

