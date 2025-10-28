import math
import config
from collections import deque


class Scaler:
	"""
	Utility class for scaling values between PLC raw range and engineering units.
	"""
	def __init__(self, raw_min: int, raw_max: int, eng_min: float, eng_max: float):
		self.raw_min = raw_min
		self.raw_max = raw_max
		self.eng_min = eng_min
		self.eng_max = eng_max

		# Precompute scale factors for speed
		self.raw_span = self.raw_max - self.raw_min
		self.eng_span = self.eng_max - self.eng_min

	def to_engineering(self, raw_value: int) -> float:
		"""
		Convert a PLC raw value to engineering units.
		"""
		scaled = ((raw_value - self.raw_min) / self.raw_span) * self.eng_span + self.eng_min
		return scaled

	def to_raw(self, eng_value: float) -> int:
		"""
		Convert engineering units to PLC raw value.
		Returns integer suitable for writing to PLC.
		"""
		scaled = ((eng_value - self.eng_min) / self.eng_span) * self.raw_span + self.raw_min
		return int(round(scaled))

	def clamp_eng(self, value: float) -> float:
		"""
		Clamp engineering value within valid engineering range.
		"""
		return max(min(value, self.eng_max), self.eng_min)

	def clamp_raw(self, value: int) -> int:
		"""
		Clamp raw PLC value within valid raw range.
		"""
		return int(max(min(value, self.raw_max), self.raw_min))

	def __repr__(self):
		return (f"Scaler(raw=({self.raw_min},{self.raw_max}), "
		        f"eng=({self.eng_min},{self.eng_max}))")


class MovingAverage:
	def __init__(self, size):
		self.q:deque = deque()
		self.window_size = size
		self.sum = 0

	def add(self, e):
		v = float(e)
		self.q.append(v)
		self.sum += v
		if len(self.q) > self.window_size:
			self.sum -= self.q.popleft()

	@property
	def mean(self) -> float:
		if not self.q:
			return 0.0
		return self.sum / len(self.q)

	def __str__(self):
		return str(list(self.q))


def calc_pv(cfg, kiln_data):
	# C*A2*sqrt(
	#   (
	#       2*Z*R*T1/M * (K/(k-1)) * ( (P2by1)**(2/k) - (P2by1)**( (K+1)/K ) )
	#   )
	#   )*1000

	c = cfg.c
	a2 = cfg.a2
	z = cfg.z
	r = cfg.r
	m = cfg.m
	k = cfg.k

	t = kiln_data.temp
	p2by1 = kiln_data.p2 / kiln_data.p2
	return c * a2 * math.sqrt(
		(2 * z * r * t / m) *
        (k / (k - 1)) *
        ((p2by1 ** (2 / k)) - (p2by1 ** ((k + 1) / k))) *
        1000)

