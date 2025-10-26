from typing import Optional


class FanDrive:
	def __init__(self, cfg):
		self.demanded_rpm = 0
		self.run_rpm = 0
		self.cfg = None
		self.set_cfg(cfg)

	def set_cfg(self, cfg):
		self.cfg = cfg

	@property
	def rpm(self) -> float:
		return self.demanded_rpm

	def set_output(self, percent):
		self.demanded_rpm = percent * (self.cfg.pid_max_rpm - self.cfg.pid_min_rpm) + self.cfg.pid_min_rpm

	def set_rpm(self, rpm):
		self.demanded_rpm = rpm

	def off(self):
		self.demanded_rpm = 0