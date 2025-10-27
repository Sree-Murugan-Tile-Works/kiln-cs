import queue
import threading
import logging
import time
import sqlite3


def queue_monitor(q: queue.Queue, stop_e: threading.Event, high_level: int, discard_count: int = 100):
    logging.info("Queue Monitor Thread starting...")
    while not stop_e.is_set():
        try:
            current_size = q.qsize()
            if current_size > high_level:
                logging.warning(f"Queue size exceeding high level; discarding {discard_count} oldest items.")
                for _ in range(discard_count):
                    try:
                        q.get_nowait()  # Discard oldest
                    except queue.Empty:
                        break
        except Exception as exc:
            logging.error(f"Queue monitor error: {exc}")

        time.sleep(5)
    logging.error("Queue Monitor Thread exit.")


def db_writer(dq:queue.Queue, stop_e: threading.Event, db):
    logging.info("DB_Writer Thread starting...")
    conn = None
    try:
        conn = sqlite3.connect(db, timeout=10, isolation_level=None)  # autocommit mode
        cur = conn.cursor()

        cur.execute("PRAGMA journal_mode=WAL;")
        # Ensure the table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kiln_data (
                timestamp TEXT PRIMARY KEY,        -- ISO8601 timestamp (e.g. 2025-10-27T20:15:00)
                q_value REAL,                      -- Volumetric Flow rate (Measured)
                temp REAL,                         -- Temperature
                pressure1 REAL,                    -- Pressure sensor 1
                pressure2 REAL,                    -- Pressure sensor 2
                pid_out REAL,                      -- PID controller output
                demanded_rpm REAL,                 -- Motor speed
                cmd_rpm REAL,                      -- Commanded setpoint
                command TEXT,                      -- Command Text
                remarks TEXT                       -- Optional diagnostic / extra data
            );
        """)

        while not stop_e.is_set() or not dq.empty():
            try:
                item = dq.get(timeout=5)
            except queue.Empty:
                continue
            try:
                plc_data = item.get('plc_data')
                cur.execute(
                    "INSERT INTO kiln_data (timestamp, q_value, temp, pressure1, pressure2, pid_out, "
                            "demanded_rpm, cmd_rpm, command, remarks) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (item.get('timestamp'), plc_data.q, plc_data.temp, plc_data.p1, plc_data.p2,
                                item.get('pid_out'), item.get('demanded_rpm'), item.get('cmd_rpm'), item.get('cmd'), "")
                )
                insert_sql = """
                             INSERT INTO kiln_data (timestamp, q_value, temp, pressure1, pressure2, pid_out,
                                                    demanded_rpm, cmd_rpm, command, remarks)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                             ON CONFLICT(timestamp) DO UPDATE SET
                                    q_value      = excluded.q_value,
                                    temp         = excluded.temp,
                                    pressure1    = excluded.pressure1,
                                    pressure2    = excluded.pressure2,
                                    pid_out      = excluded.pid_out,
                                    demanded_rpm = excluded.demanded_rpm,
                                    cmd_rpm      = excluded.cmd_rpm,
                                    command      = excluded.command,
                                    remarks      = excluded.remarks;
                             """
                plc = item.get('plc_data')
                q_val        = getattr(plc, 'q', None)
                temp         = getattr(plc, 'temp', None)
                p1           = getattr(plc, 'p1', None)
                p2           = getattr(plc, 'p2', None)
                pid_out      = item.get('pid_out')
                demanded_rpm = item.get('demanded_rpm')
                cmd_rpm      = item.get('cmd_rpm')
                command      = item.get('cmd')
                remarks      = item.get('remarks', "")
                ts           = item.get('timestamp')
                cur.execute(insert_sql, (ts, q_val, temp, p1, p2, pid_out,
                                         demanded_rpm, cmd_rpm, command, remarks))

            except sqlite3.OperationalError as e:
                logging.exception(f"SQLite operational error on insert: {e}")

            except Exception as e:
                logging.exception(f"DB insert failed: {e}")


    except Exception as e:
        logging.exception(f"DB_Writer Thread fatal error: {e}")
    finally:
        if conn:
            conn.close()

    logging.error("DB_Writer Thread exit.")