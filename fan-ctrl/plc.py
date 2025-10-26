from dataclasses import dataclass
import fins


class OmronPLCFinsConnection:
	def __init__(self):
		self.fins_con = None
		self.com_ok = None
		self.connection_ip = None
		self.connection_port = None
		self.dest_node_address = 1
		self.src_node_address = 25

	def connect(self):
		self.fins_con = fins.tcp.TCPFinsConnection()
		self.fins_con.connect(self.connection_ip, self.connection_port)

	def read_dm(self, d_addr, count):
		pass

	def write_dm(self, d_addr, data):
		pass

	def close(self):
		if self.fins_con:
			self.fins_con.close()
			self.fins_con = None

	def is_ok(self):
		return True if (self.fins_con and self.com_ok) else False

	def __del__(self):
		self.close()


@dataclass
class KilnData:
	p1: float
	p2: float
	temp: float
	q: float
	motor_rpm: int


class KilnPLC:
	def __init__(self, cfg):
		self.fins_con = OmronPLCFinsConnection()
		self.data:KilnData = KilnData(0,0,0,0,0)
		self.cfg = None
		self.set_cfg(cfg)

	def set_cfg(self, cfg):
		self.cfg = cfg

	def read(self):
		pass

	def write(self):
		pass
