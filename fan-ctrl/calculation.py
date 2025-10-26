import math
import config

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

def calc_pv(P2by1, T):
	# C*A2*sqrt((2*Z*R*T1/M*(K/(k-1))*((P2by1)**(2/k)-(P2by1)**((K+1/K))))*1000
	sr = config.srr_constant()
	C=sr.C
	A2=sr.A2
	Z= sr.Z
	R= sr.R
	M = sr.M
	K = sr.K

	return C * A2 * math.sqrt(
		(2 * Z * R * T / M) *
        (K / (K - 1)) *
        ((P2by1 ** (2 / K)) - (P2by1 ** ((K + 1) / K))) *
        1000)