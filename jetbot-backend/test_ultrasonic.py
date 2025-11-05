"""
Lightweight test script for ultrasonic sensor.
Takes a few readings and displays the results.
"""
import time
from jetbot import UltrasonicSensor


def test_ultrasonic():
    """Test ultrasonic sensor with a few readings."""
    print("="*50)
    print("Ultrasonic Sensor Test")
    print("="*50)
    
    # Initialize sensor
    print("\nInitializing ultrasonic sensor...")
    try:
        sensor = UltrasonicSensor()
        print("Sensor initialized\n")
    except Exception as e:
        print(f"Failed to initialize sensor: {e}")
        return
    
    # Take a few readings
    num_readings = 5
    print(f"Taking {num_readings} readings...\n")
    
    readings = []
    for i in range(num_readings):
        try:
            distance = sensor.read_distance()
            if distance is not None:
                readings.append(distance)
                print(f"Reading {i+1}: {distance:.3f}m ({distance*100:.1f}cm)")
            else:
                print(f"Reading {i+1}: Out of range")
        except Exception as e:
            print(f"Reading {i+1}: Error - {e}")
        
        # Small delay between readings
        if i < num_readings - 1:
            time.sleep(0.5)
    
    # Summary
    print("\n" + "-"*50)
    if readings:
        avg_distance = sum(readings) / len(readings)
        min_distance = min(readings)
        max_distance = max(readings)
        
        print(f"Summary:")
        print(f"  Valid readings: {len(readings)}/{num_readings}")
        print(f"  Average: {avg_distance:.3f}m ({avg_distance*100:.1f}cm)")
        print(f"  Min: {min_distance:.3f}m ({min_distance*100:.1f}cm)")
        print(f"  Max: {max_distance:.3f}m ({max_distance*100:.1f}cm)")
    else:
        print("No valid readings obtained")
    
    print("="*50)
    
    # Cleanup
    try:
        sensor.cleanup()
        print("\nSensor cleaned up")
    except Exception as e:
        print(f"\nCleanup warning: {e}")


if __name__ == "__main__":
    try:
        test_ultrasonic()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")

