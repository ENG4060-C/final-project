"""
HC-SR04 Ultrasonic Distance Sensor for JetBot (robust timing).
Drop-in replacement for your class to reduce N/A readings.
"""
import time
import atexit
import traitlets
from traitlets.config.configurable import Configurable
from statistics import median

try:
    import Jetson.GPIO as GPIO
except ImportError:
    raise ImportError("Jetson.GPIO not found. Install with: pip install Jetson.GPIO")


# Default pins (BCM)
DEFAULT_TRIGGER_PIN = 12  # phys 32 (remember pinmux once per boot)
DEFAULT_ECHO_PIN    = 25  # phys 22 (through level shifter/divider)

# Sensor + timing
SPEED_OF_SOUND_M_S   = 343.0
MIN_DISTANCE_M       = 0.02
MAX_DISTANCE_M       = 4.00

# Tunables (robust defaults)
TRIGGER_PULSE_US     = 25        # 20–30 µs is reliable
START_TIMEOUT_MS     = 10        # wait for echo to go HIGH (~8–10 ms)
ECHO_TIMEOUT_MS      = 40        # max echo high width (~> 4 m ~ 38 ms)
MIN_INTER_PING_MS    = 60        # sensor needs ~60 ms quiet time
RETRIES              = 2         # extra attempts before declaring N/A
RETRY_GAP_MS         = 4         # small pause between retries

def _ns():
    return time.perf_counter_ns()

def _sleep_ms(ms):
    time.sleep(ms/1000.0)


class UltrasonicSensor(Configurable):
    """
    Robust HC-SR04 controller for Jetson.
    Wiring:
      VCC -> 5V (phys 4)
      GND -> GND (phys 6/9/14/20/25/30/34/39)
      TRIG -> BCM 12 (phys 32)  [pinmux needed once per boot]
      ECHO -> BCM 25 (phys 22)  [level-shifted to 3.3V]
    """
    trigger_pin = traitlets.Integer(default_value=DEFAULT_TRIGGER_PIN).tag(config=True)
    echo_pin    = traitlets.Integer(default_value=DEFAULT_ECHO_PIN).tag(config=True)

    def __init__(self, trigger_pin=None, echo_pin=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if trigger_pin is not None:
            self.trigger_pin = trigger_pin
        if echo_pin is not None:
            self.echo_pin = echo_pin

        self._initialized = False
        self._last_ping_ns = 0
        self._last_good_m = None   # use to fill if desired
        self._setup()
        atexit.register(self.cleanup)

    def _setup(self):
        if self._initialized:
            return
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.trigger_pin, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.echo_pin, GPIO.IN)
        time.sleep(0.1)  # settle
        self._initialized = True

    # ---- core low-level read (no filtering) ----
    def _read_once(self):
        """
        Single ping with strict timing.
        Returns (status, distance_m_or_None)
          status in {"ok","timeout_wait_high","timeout_wait_low","range_low","range_high"}
        """
        # enforce inter-ping quiet
        now = _ns()
        gap_ns = (MIN_INTER_PING_MS * 1_000_000) - (now - self._last_ping_ns)
        if gap_ns > 0:
            time.sleep(gap_ns / 1_000_000_000)

        # trigger pulse (25 µs)
        GPIO.output(self.trigger_pin, GPIO.HIGH)
        time.sleep(TRIGGER_PULSE_US / 1_000_000.0)
        GPIO.output(self.trigger_pin, GPIO.LOW)

        t_start = _ns()
        # wait for echo to go HIGH (start)
        while GPIO.input(self.echo_pin) == 0:
            if (_ns() - t_start) > START_TIMEOUT_MS * 1_000_000:
                self._last_ping_ns = _ns()
                return ("timeout_wait_high", None)

        t_high = _ns()
        # wait for echo to go LOW (end)
        while GPIO.input(self.echo_pin) == 1:
            if (_ns() - t_high) > ECHO_TIMEOUT_MS * 1_000_000:
                self._last_ping_ns = _ns()
                return ("timeout_wait_low", None)

        t_low = _ns()
        self._last_ping_ns = t_low

        dur_s = (t_low - t_high) / 1_000_000_000.0
        d_m = (dur_s * SPEED_OF_SOUND_M_S) / 2.0

        if d_m < MIN_DISTANCE_M:
            return ("range_low", None)
        if d_m > MAX_DISTANCE_M:
            return ("range_high", None)
        return ("ok", d_m)

    # ---- public read with retries + optional last-good fill ----
    def read_distance(self, use_last_good=True):
        """
        Returns float distance in meters or None.
        Retries to reduce N/A. If use_last_good and still N/A, returns last good value.
        """
        for attempt in range(RETRIES + 1):
            status, val = self._read_once()
            if status == "ok":
                self._last_good_m = val
                return val
            # quick recovery gaps help after timeouts
            _sleep_ms(RETRY_GAP_MS)

        # All attempts failed
        return self._last_good_m if use_last_good else None

    def read_distance_avg(self, samples=3):
        """
        Median of multiple reads (already robust with retries).
        Returns meters or None (or last-good if enabled in read_distance).
        """
        vals = []
        for _ in range(samples):
            v = self.read_distance(use_last_good=False)
            if v is not None:
                vals.append(v)
        if not vals:
            # fall back to last-good if we have one
            return self._last_good_m
        m = median(vals)
        self._last_good_m = m
        return m

    def cleanup(self):
        if self._initialized:
            try:
                GPIO.cleanup([self.trigger_pin, self.echo_pin])
            except Exception:
                pass
            self._initialized = False

    def __del__(self):
        self.cleanup()
