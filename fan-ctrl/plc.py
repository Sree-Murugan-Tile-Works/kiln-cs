from dataclasses import dataclass
from typing import Optional
import socket
import time

import fins.tcp


SOCKET_TIMEOUT = 2
MAX_RETRIES = 3
BASE_BACKOFF = 3
BACKOFF = 0.5

@dataclass
class KilnData:
	p1: float
	p2: float
	temp: float
	q: float
	motor_rpm: int


class KilnPLC:
	def __init__(self, cfg):
		self.fins_con:Optional[fins.tcp.TCPFinsConnection] =  None
		self.com_ok = None
		self.data:KilnData = KilnData(0,0,0,0,0)
		self.cfg = None
		self.set_cfg(cfg)

	def set_cfg(self, cfg):
		self.cfg = cfg

	def connect(self):
		last_e = None
		self.close()
		retries = 0
		while retries < MAX_RETRIES:
			try:
				self.fins_con = fins.tcp.TCPFinsConnection()
				self.fins_con.connect(self.cfg.plc_ip, self.cfg.plc_fins_port, connection_timeout=SOCKET_TIMEOUT)
				self.com_ok = True
				return

			except OSError as e:
				last_e = e
				self.com_ok = False

				try:
					self.fins_con.fins_socket.close()
				except (OSError, socket.timeout):
					pass

				self.fins_con = None
				retries += 1

			if retries < (MAX_RETRIES - 1):
				delay = BASE_BACKOFF + BACKOFF * retries
				time.sleep(delay)

		raise ConnectionError (
				f"Failed to connect to {self.cfg.plc_ip}:{self.cfg.plc_fins_port} after {MAX_RETRIES} attempts"
				) from last_e

	def write_watchdog(self):
		pass
		self.com_ok = True

	def is_ok(self):
		return True if (self.fins_con and self.com_ok) else False

	def close(self):
		if self.fins_con:
			c, self.fins_con = self.fins_con, None
			try:
				c.fins_socket.close()
			except OSError:
				pass

	def __del__(self):
		self.close()

	def read(self):
		pass
		self.com_ok = True

	def write(self):
		pass
		self.com_ok = True

	def read_dm(self, d_addr, count):
		pass
		self.com_ok = True

	def write_dm(self, d_addr, data):
		pass
		self.com_ok = True

