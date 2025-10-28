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
DATA_DB = "../data/data.db"
QUEUE_MAX = 10000

logging.basicConfig(level=logging.INFO)

data_queue = queue.Queue(maxsize=QUEUE_MAX)
stop_event = threading.Event()


def daq_pid(data_q: queue.Queue, stop_e: threading.Event):
    logging.info(f"DAQ_PID Thread starting, Loading config from {CONFIG_DB}...")
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
    q_avg: calculation.MovingAverage = calculation.MovingAverage(cfg.q_average_count)

    next_time = time.monotonic()
    next_reload = time.monotonic() + RELOAD_CFG_IN
    last_comm = True
    last_command = ""
    pid_out = 0

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
        kiln_plc.read_all()
        read_time = time.monotonic()

        if not kiln_plc.com_ok:
            # write to log
            logging.error(f"Error communicating with from PLC.")
            last_comm = False

        else:

            if not last_comm:
                last_comm = True
                logging.info("PLC Com OK.")

            if last_command != cfg.cur_cmd:
                last_command = cfg.cur_cmd
                logging.info(f"Command {cmd.command} received.")

            q_avg.add(kiln_plc.data.q)

            if cmd.command == "PID":
                # calc PID on mean
                pid_out = pid_ctrl.compute(q_avg.mean, read_time)
                fan_drive_ctl.set_output_percent(pid_out)

            elif cmd.command == "MAN":
                fan_drive_ctl.set_rpm(cmd.value)

            elif cmd.command == "OFF":
                fan_drive_ctl.off()

            kiln_plc.data.motor_rpm = fan_drive_ctl.commanded_rpm

            # write to PLC
            kiln_plc.write()
            kiln_plc.write_watchdog()

            # write to db
            try:
                data_q.put_nowait({'plc_data': kiln_plc.data, 'cmd':cmd.command, "pid_out":pid_out,
                                   "demanded_rpm":fan_drive_ctl.demanded_rpm,
                                   "cmd_rpm":fan_drive_ctl.commanded_rpm, 'timestamp': read_time})
            except queue.Full:
                logging.warning("Data queue full; dropping data")

        # sleep
        next_time += cfg.scan_interval
        sleep_time = max(0, next_time - time.monotonic())
        time.sleep(sleep_time)

    logging.error(f"DAQ_PID Thread exit.")


def signal_handler(sig, frame):
    sig_name = signal.Signals(sig).name
    logging.info(f"Received signal: {sig_name} ({sig})")
    stop_event.set()


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    t_daq_pid = threading.Thread(target=daq_pid, args=(data_queue,stop_event))
    t_db = threading.Thread(target=dbwriter.db_writer, args=(data_queue,stop_event,DATA_DB))
    t_monitor = threading.Thread(target=dbwriter.queue_monitor, args=(data_queue, stop_event, int(QUEUE_MAX * 0.9)))
    t_monitor.start()
    t_daq_pid.start()
    t_db.start()

    t_daq_pid.join()
    t_db.join()
    t_monitor.join()