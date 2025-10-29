import time
import traitlets
from traitlets.config.configurable import SingletonConfigurable
from smbus2 import SMBus

from Adafruit_MotorHAT import Adafruit_MotorHAT
import qwiic

from .motor import Motor

def probe_addr_read(bus, addr):
    try:
        # Cheap read probe; many devices tolerate a simple byte read
        bus.read_byte(addr)
        return True
    except Exception:
        return False

def probe_reg(bus, addr, reg=0x00):
    try:
        bus.read_byte_data(addr, reg)
        return True
    except Exception:
        return False

def scan_bus(busnum):
    found = set()
    try:
        with SMBus(busnum) as bus:
            for addr in range(0x03, 0x78):
                if probe_addr_read(bus, addr):
                    found.add(addr)
    except FileNotFoundError:
        pass
    return found

class Robot(SingletonConfigurable):
    left_motor = traitlets.Instance(Motor)
    right_motor = traitlets.Instance(Motor)

    i2c_bus = traitlets.Integer(default_value=7).tag(config=True)
    left_motor_channel  = traitlets.Integer(default_value=1).tag(config=True)
    left_motor_alpha    = traitlets.Float(default_value=1.0).tag(config=True)
    right_motor_channel = traitlets.Integer(default_value=2).tag(config=True)
    right_motor_alpha   = traitlets.Float(default_value=1.0).tag(config=True)

    def __init__(self, *args, **kwargs):
        super(Robot, self).__init__(*args, **kwargs)

        addrs = scan_bus(self.i2c_bus)

        # Explicit PCA9685 probe (MODE1 register) on 0x60..0x67
        have_pca9685 = False
        try:
            with SMBus(self.i2c_bus) as bus:
                for a in range(0x60, 0x68):
                    if probe_reg(bus, a, 0x00):
                        have_pca9685 = True
                        break
        except Exception:
            pass

        if have_pca9685:
            self.motor_driver = Adafruit_MotorHAT(i2c_bus=self.i2c_bus)
        elif 0x5D in addrs:
            self.motor_driver = qwiic.QwiicScmd()
            self.motor_driver.enable()
        else:
            raise RuntimeError(f'No supported motor driver found on I2C bus {self.i2c_bus}. '
                               f'Found addresses: {[hex(a) for a in sorted(addrs)]}')

        self.left_motor  = Motor(self.motor_driver, channel=self.left_motor_channel,  alpha=self.left_motor_alpha)
        self.right_motor = Motor(self.motor_driver, channel=self.right_motor_channel, alpha=self.right_motor_alpha)

    def set_motors(self, left_speed, right_speed):
        self.left_motor.value  = left_speed
        self.right_motor.value = right_speed

    def forward(self, speed=1.0, duration=None):
        self.left_motor.value = speed
        self.right_motor.value = speed
        if duration is not None:
            time.sleep(duration); self.stop()

    def backward(self, speed=1.0, duration=None):
        self.left_motor.value = -speed
        self.right_motor.value = -speed
        if duration is not None:
            time.sleep(duration); self.stop()

    def left(self, speed=1.0, duration=None):
        self.left_motor.value = -speed
        self.right_motor.value = speed
        if duration is not None:
            time.sleep(duration); self.stop()

    def right(self, speed=1.0, duration=None):
        self.left_motor.value = speed
        self.right_motor.value = -speed
        if duration is not None:
            time.sleep(duration); self.stop()

    def stop(self):
        self.left_motor.value = 0.0
        self.right_motor.value = 0.0
