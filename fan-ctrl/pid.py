from utils import AttrDict


class PIDController:
	def __init__(self, cfg):
		"""
		Initialize the PID controller.
		"""
		self.cfg = None
		self.kp = self.ki = self.kd = self.set_point = None
		self._previous_error = 0.0
		self._integral = 0.0
		self._last_time = None
		self.set_cfg(cfg)

	def set_cfg(self, cfg):
		self.kp = cfg.kp
		self.kp = cfg.kp
		self.kp = cfg.kp
		self.set_point = cfg.set_point

	def reset(self):
		"""
		Reset the PID controller (integral and last error).
		"""
		self._previous_error = 0.0
		self._integral = 0.0
		self._last_time = None

	def compute(self, process_variable: float, current_time: float):
		"""
		Compute the control output.

		:param process_variable: The current value of the process being controlled
		:param current_time: The current timestamp
		:return: Control output
		"""
		# Calculate error
		error = self.set_point - process_variable

		# Calculate time difference
		if self._last_time is None:
			delta_time = 0
			self._last_time = current_time
		else:
			delta_time = current_time - self._last_time
			self._last_time = current_time

		# Proportional term
		proportional = self.kp * error

		# Integral term
		self._integral += error * delta_time
		integral = self.ki * self._integral

		# Derivative term
		if delta_time > 0:
			derivative = self.kd * (error - self._previous_error) / delta_time
		else:
			derivative = 0.0

		# Remember the current error for the next derivative calculation
		self._previous_error = error

		# Calculate total output
		output = proportional + integral + derivative
		return output
