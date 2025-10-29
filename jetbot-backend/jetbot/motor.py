# Unified Motor for Adafruit MotorHAT (PCA9685) or SparkFun Qwiic SCMD
import atexit
import traitlets
from traitlets.config.configurable import Configurable
from Adafruit_MotorHAT import Adafruit_MotorHAT

class Motor(Configurable):
    value = traitlets.Float()
    alpha = traitlets.Float(default_value=1.0).tag(config=True)
    beta  = traitlets.Float(default_value=0.0).tag(config=True)

    def __init__(self, driver, channel, *args, **kwargs):
        super(Motor, self).__init__(*args, **kwargs)
        self._driver  = driver
        self.channel  = channel
        self._kind    = 'unknown'
        self._motor   = None

        # Detect driver kind by capabilities
        if hasattr(driver, 'getMotor'):
            # Adafruit MotorHAT (PCA9685 @ 0x60..0x67)
            self._kind  = 'adafruit'
            self._motor = self._driver.getMotor(channel)
            if channel == 1:
                self._ina, self._inb = 1, 0
            elif channel == 2:
                self._ina, self._inb = 2, 3
            elif channel == 3:
                self._ina, self._inb = 4, 5
            else:
                self._ina, self._inb = 6, 7
        elif hasattr(driver, 'set_drive') and hasattr(driver, 'enable'):
            # SparkFun Qwiic SCMD
            self._kind = 'sparkfun'
        else:
            raise RuntimeError('Unknown motor driver type')

        atexit.register(self._release)

    @traitlets.observe('value')
    def _observe_value(self, change):
        self._write_value(change['new'])

    def _write_value(self, value: float):
        v = self.alpha * float(value) + self.beta
        v = max(-1.0, min(1.0, v))

        if self._kind == 'adafruit':
            mapped = int(255.0 * v)
            speed  = min(max(abs(mapped), 0), 255)
            self._motor.setSpeed(speed)
            if mapped < 0:
                self._motor.run(Adafruit_MotorHAT.FORWARD)
                self._driver._pwm.setPWM(self._ina, 0, 0)
                self._driver._pwm.setPWM(self._inb, 0, speed * 16)
            else:
                self._motor.run(Adafruit_MotorHAT.BACKWARD)
                self._driver._pwm.setPWM(self._ina, 0, speed * 16)
                self._driver._pwm.setPWM(self._inb, 0, 0)

        elif self._kind == 'sparkfun':
            # SCMD expects -255..255; sign sets direction
            speed = int(255 * v)
            # A=0, B=1; channel is 1/2 in JetBot API
            mnum = 0 if self.channel == 1 else 1
            direction = 0 if speed >= 0 else 1
            self._driver.set_drive(mnum, direction, abs(speed))
            self._driver.enable()

    def _release(self):
        try:
            if self._kind == 'adafruit':
                self._motor.run(Adafruit_MotorHAT.RELEASE)
                self._driver._pwm.setPWM(self._ina, 0, 0)
                self._driver._pwm.setPWM(self._inb, 0, 0)
            elif self._kind == 'sparkfun':
                # stop both channels for safety
                self._driver.set_drive(0, 0, 0)
                self._driver.set_drive(1, 0, 0)
                self._driver.disable()
        except Exception:
            pass
