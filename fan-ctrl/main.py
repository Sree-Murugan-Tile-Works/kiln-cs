import time
import queue
import threading
import signal
import logging

import command
import plc
import pid
import fan_drive
import config
import calculation
import dbwriter


RELOAD_CFG_IN = 60
CONFIG_DB = "../data/config.db"
logging.basicConfig(level=logging.INFO)
QUEUE_MAX = 10000

data_queue = queue.Queue(maxsize=QUEUE_MAX)
stop_event = threading.Event()


def daq_pid(data_q: queue.Queue, stop_e: threading.Event):
    # load config
    cfg = config.load_config_from_db(CONFIG_DB)

    def parse_cmd() -> command.Command:
        try:
            cur_cmd = command.Command(cfg.cur_cmd)
        except ValueError:
            # Log that command is wrong
            # Turn fan off
            cur_cmd = command.Command("OFF")
        return cur_cmd

    cmd: command.Command | None = parse_cmd()
    kiln_plc: plc.KilnPLC = plc.KilnPLC(cfg)
    pid_ctrl: pid.PIDController = pid.PIDController(cfg)
    fan_drive_ctl: fan_drive.FanDrive = fan_drive.FanDrive(cfg)

    next_time = time.monotonic()
    next_reload = time.monotonic() + RELOAD_CFG_IN

    while not stop_e.is_set():
        if time.monotonic() >= next_reload:
            # re-load control profile
            cfg = config.load_config_from_db(CONFIG_DB)
            kiln_plc.set_cfg(cfg)
            pid_ctrl.set_cfg(cfg)
            fan_drive_ctl.set_cfg(cfg)
            cmd = parse_cmd()
            next_reload += RELOAD_CFG_IN

        # read data from PLC
        kiln_plc.read()
        read_time = time.monotonic()

        if not kiln_plc.com_ok:
            # write to log
            print("error")

        else:
            # do computation on read values and command
            q_value = calculation.calc_pv(cfg, kiln_plc.data)

            if cmd.command == "PID":
                # calc PID
                pid_out = pid_ctrl.compute(q_value, read_time)
                fan_drive_ctl.set_output(pid_out)

            elif cmd.command == "MAN":
                fan_drive_ctl.set_rpm(cmd.value)

            elif cmd.command == "OFF":
                fan_drive_ctl.off()

            kiln_plc.data.motor_rpm = fan_drive_ctl.run_rpm

            # write to PLC
            kiln_plc.write()
            kiln_plc.write_watchdog()

            # write to db
            try:
                data_q.put_nowait({'plc_data': kiln_plc.data, 'pv': q_value, 'timestamp': read_time})
            except queue.Full:
                logging.warning("Data queue full; dropping data")

        # sleep
        next_time += cfg.scan_interval
        sleep_time = max(0, next_time - time.monotonic())
        time.sleep(sleep_time)


def signal_handler(sig, frame):
    stop_event.set()


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    t_daq_pid = threading.Thread(target=daq_pid, args=(data_queue,stop_event))
    t_db = threading.Thread(target=dbwriter.db_writer, args=(data_queue,stop_event))
    t_monitor = threading.Thread(target=dbwriter.queue_monitor, args=(data_queue, stop_event, int(QUEUE_MAX * 0.9)))
    t_monitor.start()
    t_daq_pid.start()
    t_db.start()

    t_daq_pid.join()
    t_db.join()
    t_monitor.join()