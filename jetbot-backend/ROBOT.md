# JetBot Robot Documentation

## Motor Speed Values Explained

### Value Range
- **Range**: `0.0` to `1.0` (normalized motor speed)
- **0.0** = stopped
- **0.5** = half speed
- **1.0** = full speed

### Current Implementation Limits
- **MIN_MOTOR_VALUE**: `0.3` (minimum to overcome static friction)
- **MAX_MOTOR_VALUE**: `1.0` (full speed)

---

## Calibrated Values

### Motor Speed Factor
- **MOTOR_SPEED_FACTOR**: `0.1827` m/s per motor unit
- **Calibration**: 0.274m traveled in 3s at motor=0.5
- **Example**: motor_value=0.5 → ~0.091 m/s (9.1 cm/s)

### Balance Correction
- **LEFT_MOTOR_OFFSET**: `0.0085` (correction for weight imbalance)
- Applied only during forward/backward movement
- At max speed (1.0), overflow is handled by reducing right motor

---

## RobotController API

### `move_distance(distance_m, robot_speed=0.5)`

Move robot forward/backward for approximately the specified distance.

**Parameters:**
- `distance_m`: Distance in meters (+ = forward, - = backward)
- `robot_speed`: Motor speed value 0.0 to 1.0 (default: 0.5)

**Example:**
```python
controller = RobotController()

# Move forward 0.5m at half speed
controller.move_distance(0.5, 0.5)

# Move backward 1.0m at full speed
controller.move_distance(-1.0, 1.0)
```

**Notes:**
- Time-based estimation without encoder feedback
- Actual distance may vary ±20% due to wheel slip, battery, surface
- Balance correction applied automatically for straight movement

### `rotate(angle_degrees, robot_speed=0.5)`

Rotate robot in place by specified angle.

**Parameters:**
- `angle_degrees`: Angle in degrees (+ = right turn, - = left turn)
- `robot_speed`: Motor speed value 0.0 to 1.0 (default: 0.5)

**Example:**
```python
# Rotate 90 degrees right at half speed
controller.rotate(90, 0.5)

# Rotate 45 degrees left at full speed
controller.rotate(-45, 1.0)
```

**Notes:**
- Uses smooth deceleration to reduce momentum overshoot
- Overshoot correction compensates for momentum build-up on larger rotations
- No balance correction needed (one wheel forward, one backward)

---

## Hardware Configuration

### Current Setup
- **I2C Bus**: 7
- **Left Motor Channel**: 1
- **Right Motor Channel**: 2
- **Camera Resolution**: 1640x1232

### Ultrasonic Sensor (HC-SR04)

Working setup configuration:

**Power:**
- **VCC**: 5V (Physical pin 4)
- **GND**: Physical pin 9
- Common ground shared with Jetson

**Signal Pins:**
- **TRIG**: BCM GPIO 12 (Physical pin 32)
  - Pinmux configuration: `sudo busybox devmem 0x2434080 w 0x5`
- **ECHO**: BCM GPIO 25 (Physical pin 22)
  - Connected through resistor divider (level-shifted to 3.3V)

**Notes:**
- Powered at 5V for full range
- ECHO pin must be level-shifted from 5V to 3.3V for Jetson GPIO compatibility
- TRIG pin requires pinmux configuration before use (run devmem command above)
- Test script: `test_ultrasonic.py`

## Implementation Details

### Balance Correction Logic

For forward movement:
```python
left_motor = motor_value + LEFT_MOTOR_OFFSET
right_motor = motor_value

# Handle overflow at max speed
if left_motor > 1.0:
    overflow = left_motor - 1.0
    left_motor = 1.0
    right_motor = max(0.0, motor_value - overflow)
```

For backward movement, same logic applies with negative values.

### Rotation Calculation

Rotation uses differential drive kinematics with smooth deceleration:
- **Wheelbase**: 0.0540m (calibrated)
- Distance per wheel: `angle_radians * wheelbase / 2`
- One wheel forward, one backward at same speed
- Smooth deceleration reduces momentum overshoot
- Overshoot correction applied for angles > 90° (compensates for momentum build-up)

**Accuracy**: ±5° for angles 90-720°, perfect for 90-180°

---

## Calibration Results

### Distance Calibration
- **Test**: Motor value 0.5 for 3 seconds
- **Result**: Traveled 0.274m (27.4cm)
- **Calculated Speed**: 0.0913 m/s
- **MOTOR_SPEED_FACTOR**: 0.1827 m/s per motor unit

### Balance Calibration
- **Test**: Multiple motor values with different offsets
- **Optimal Offset**: 0.0085 added to left motor
- **Result**: Straight movement achieved

---
