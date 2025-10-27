import logging
from dataclasses import dataclass
from typing import Optional
import socket
import time

import fins.tcp

import calculation


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


class KilnPLC:
	def __init__(self, cfg):
		self.fins_con:Optional[fins.tcp.TCPFinsConnection] =  None
		self.com_ok = None
		self.data:KilnData = KilnData(0,0,0,0,0)
		self.scl_p1 = None
		self.scl_p2 = None
		self.scl_t = None
		self.cfg = None
		self.set_cfg(cfg)

	def set_cfg(self, cfg):
		self.cfg = cfg
		self.scl_p1 = calculation.Scaler(cfg.p1_plc_min, cfg.p1_plc_max, cfg.p1_eng_min, cfg.p1_eng_max)
		self.scl_p2 = calculation.Scaler(cfg.p2_plc_min, cfg.p2_plc_max, cfg.p2_eng_min, cfg.p2_eng_max)
		self.scl_t = calculation.Scaler(cfg.t_plc_min, cfg.t_plc_max, cfg.t_eng_min, cfg.t_eng_max)

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

	def read_all(self):
		# read DM registers
		p1_raw = 0
		p2_raw = 0
		t_raw = 0
		# todo: detect and handle negative values properly

		err_ai_chl = [ x[1] for x in [(p1_raw, "P1"), (p2_raw, "P2"), (t_raw, "T") ] if x[0] == self.cfg.plc_ai_error]
		if err_ai_chl:
			logging.error(f"Sensor Error(s) in AI Channels: {', '.join(err_ai_chl)}")
			self.com_ok = False
			return False
		# scale each value
		self.data.p1 = self.scl_p1(p1_raw)
		self.data.p2 = self.scl_p2(p2_raw)
		self.data.t = self.scl_t(t_raw)

		# compute q value
		self.data.q = calculation.calc_pv(self.cfg, self.data)
		self.com_ok = True
		return True

	def write(self):
		# write motor rpm in DM register
		self.com_ok = True

	def read_dm(self, d_addr, count):
		pass
		self.com_ok = True

	def write_dm(self, d_addr, data):
		pass
		self.com_ok = True

