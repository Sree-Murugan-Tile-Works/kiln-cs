from typing import Optional


class FanDrive:
	def __init__(self, cfg):
		self.demanded_rpm = 0
		self.commanded_rpm = 0
		self.cfg = None
		self.set_cfg(cfg)

	def set_cfg(self, cfg):
		self.cfg = cfg

	@property
	def rpm(self) -> float:
		return self.demanded_rpm

	def clamp_motor_rpm(self, demanded):
		return min(self.cfg.motor_max_rpm, max(demanded, self.cfg.motor_min_rpm))

	def set_output_percent(self, percent):
		self.demanded_rpm = percent * (self.cfg.pid_max_rpm - self.cfg.pid_min_rpm) + self.cfg.pid_min_rpm
		self.commanded_rpm = self.clamp_motor_rpm(self.demanded_rpm)

	def set_rpm(self, rpm):
		self.commanded_rpm = self.clamp_motor_rpm(rpm)

	def off(self):
		self.demanded_rpm = self.commanded_rpm = 0
