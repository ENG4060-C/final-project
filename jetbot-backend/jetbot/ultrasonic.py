"""
HC-SR04 Ultrasonic Distance Sensor for JetBot.
Provides distance measurement capabilities.
"""
import time
import atexit
import traitlets
from traitlets.config.configurable import Configurable
from statistics import median

try:
    import Jetson.GPIO as GPIO
except ImportError:
    raise ImportError(
        "Jetson.GPIO not found. Please install it with: pip install Jetson.GPIO"
    )


# Default configuration for HC-SR04 sensor
# TRIG: BCM GPIO 12 (Physical pin 32)
# ECHO: BCM GPIO 25 (Physical pin 22)
# Pinmux config for TRIG: sudo busybox devmem 0x2434080 w 0x5
DEFAULT_TRIGGER_PIN = 12
DEFAULT_ECHO_PIN = 25

# HC-SR04 specifications
SPEED_OF_SOUND_M_S = 343.0  # m/s at 20°C
MIN_DISTANCE_M = 0.02  # 2cm minimum
MAX_DISTANCE_M = 4.0   # 400cm maximum
ECHO_TIMEOUT_S = 0.10  # 100ms timeout for echo response


class UltrasonicSensor(Configurable):
    """
    HC-SR04 Ultrasonic Distance Sensor controller.
    
    Provides distance measurement using ultrasonic echo ranging.
    Sensor must be configured with:
    - VCC: 5V (Physical pin 4)
    - GND: Physical pin 9
    - TRIG: BCM GPIO 12 (Physical pin 32) - requires pinmux config
    - ECHO: BCM GPIO 25 (Physical pin 22) - level-shifted to 3.3V
    """
    
    trigger_pin = traitlets.Integer(default_value=DEFAULT_TRIGGER_PIN).tag(config=True)
    echo_pin = traitlets.Integer(default_value=DEFAULT_ECHO_PIN).tag(config=True)
    
    def __init__(self, trigger_pin=None, echo_pin=None, *args, **kwargs):
        """
        Initialize ultrasonic sensor.
        
        Args:
            trigger_pin: GPIO pin number for TRIGGER (BCM mode, default: 12)
            echo_pin: GPIO pin number for ECHO (BCM mode, default: 25)
        """
        super(UltrasonicSensor, self).__init__(*args, **kwargs)
        
        if trigger_pin is not None:
            self.trigger_pin = trigger_pin
        if echo_pin is not None:
            self.echo_pin = echo_pin
        
        self._initialized = False
        self._setup()
        atexit.register(self.cleanup)
    
    def _setup(self):
        """Configure GPIO pins for ultrasonic sensor."""
        if self._initialized:
            return
        
        try:
            # Set GPIO mode to BCM (GPIO numbers)
            GPIO.setmode(GPIO.BCM)
            
            # Configure TRIGGER pin as output
            GPIO.setup(self.trigger_pin, GPIO.OUT, initial=GPIO.LOW)
            
            # Configure ECHO pin as input
            GPIO.setup(self.echo_pin, GPIO.IN)
            
            # Small delay to let pins settle
            time.sleep(0.1)
            
            self._initialized = True
        except Exception as e:
            raise RuntimeError(f"Failed to initialize ultrasonic sensor: {e}")
    
    def read_distance(self, timeout=None):
        """
        Read a single distance measurement from the sensor.
        
        Args:
            timeout: Timeout in seconds (default: ECHO_TIMEOUT_S)
        
        Returns:
            float: Distance in meters, or None if timeout/error
        """
        if not self._initialized:
            self._setup()
        
        if timeout is None:
            timeout = ECHO_TIMEOUT_S
        
        # Ensure TRIGGER is LOW before starting
        GPIO.output(self.trigger_pin, GPIO.LOW)
        time.sleep(0.000005)  # 5 microseconds
        
        # Send trigger pulse (10µs HIGH, but use 20µs for reliability)
        GPIO.output(self.trigger_pin, GPIO.HIGH)
        time.sleep(0.00002)  # 20 microseconds
        GPIO.output(self.trigger_pin, GPIO.LOW)
        
        # Wait for ECHO pin to go HIGH (start of echo pulse)
        t0 = time.time()
        while GPIO.input(self.echo_pin) == GPIO.LOW:
            if time.time() - t0 > timeout:
                return None
        
        # Measure duration of HIGH pulse
        start = time.time()
        while GPIO.input(self.echo_pin) == GPIO.HIGH:
            if time.time() - start > timeout:
                return None
        
        # Calculate pulse duration
        duration = time.time() - start
        
        # Calculate distance in meters (round trip, so divide by 2)
        # distance = (pulse_duration * speed_of_sound) / 2
        distance_m = (duration * SPEED_OF_SOUND_M_S) / 2.0
        
        # Validate distance is within HC-SR04 range
        if distance_m < MIN_DISTANCE_M or distance_m > MAX_DISTANCE_M:
            return None
        
        return distance_m
    
    def read_distance_avg(self, samples=3, gap=0.02, timeout=None):
        """
        Read multiple samples and return median distance.
        
        Args:
            samples: Number of samples to take (default: 3)
            gap: Delay between samples in seconds (default: 0.02)
            timeout: Timeout per sample in seconds (default: ECHO_TIMEOUT_S)
        
        Returns:
            float: Median distance in meters, or None if no valid readings
        """
        if timeout is None:
            timeout = ECHO_TIMEOUT_S
        
        readings = []
        for _ in range(samples):
            distance = self.read_distance(timeout=timeout)
            if distance is not None:
                readings.append(distance)
            time.sleep(gap)
        
        if len(readings) == 0:
            return None
        
        # Return median value (more robust than mean for noisy sensors)
        return median(readings)
    
    def cleanup(self):
        """Clean up GPIO pins."""
        if self._initialized:
            try:
                GPIO.cleanup([self.trigger_pin, self.echo_pin])
                self._initialized = False
            except Exception:
                pass
    
    def __del__(self):
        """Ensure cleanup on deletion."""
        self.cleanup()

