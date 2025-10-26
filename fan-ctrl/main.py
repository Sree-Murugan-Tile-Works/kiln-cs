import time

import command
import plc
import pid
import fan_drive
import config


def parse_cmd():
	try:
		cur_cmd = command.Command(cfg.cur_cmd)
	except ValueError:
		# Log that command is wrong
		# Turn fan off
		cur_cmd = "OFF"
	return cur_cmd


config_db = "../data/config.db"
# load config
cfg = config.load_config_from_db(config_db)

kiln_plc:plc.KilnPLC = plc.KilnPLC(cfg)
pid:pid.PIDController = pid.PIDController(cfg)
fan_drive_ctl:fan_drive.FanDrive = fan_drive.FanDrive(cfg)
cmd: command.Command | None = parse_cmd()

next_time = time.monotonic()
RELOAD_CFG_IN = 60
next_reload = time.monotonic() + RELOAD_CFG_IN
running = True

while running:
	if time.monotonic() >= next_reload:
		# re-load control profile
		cfg = config.load_config_from_db(config_db)
		kiln_plc.set_cfg(cfg)
		pid.set_cfg(cfg)
		fan_drive_ctl.set_cfg(cfg)
		parse_cmd()
		next_reload += RELOAD_CFG_IN

	# read data from PLC
	kiln_plc.read()

	# do computation on read values and command

	if cmd.command == "PID":
		# calc PID
		pid.set_cfg(cfg)
		pid_out = pid.compute(0, 0)
		fan_drive_ctl.set_output(pid_out)

	elif cmd.command == "MAN":
		fan_drive_ctl.set_rpm(cmd.value)

	elif cmd.command == "OFF":
		fan_drive_ctl.off()

	kiln_plc.data.motor_rpm = fan_drive_ctl.run_rpm

	# write to PLC
	kiln_plc.write()

	# write to log

	# sleep
	next_time += cfg.scan_interval
	sleep_time = max(0, next_time - time.monotonic())
	time.sleep(sleep_time)