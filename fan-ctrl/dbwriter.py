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


def create_data_tables(db):
    conn = sqlite3.connect(db, timeout=10, isolation_level=None)  # autocommit mode
    cur = conn.cursor()
    # Ensure the table exists
    cur.execute("""
                CREATE TABLE kiln_data (
                    timestamp      TEXT PRIMARY KEY,      -- ISO8601 datetime string or epoch; must be UNIQUE for ON CONFLICT
                    q_value        REAL,                  -- instantaneous flow / rate value
                    q_avg          REAL,                  -- moving average of q_value
                    temp           REAL,                  -- temperature reading
                    pressure1      REAL,                  -- pressure sensor 1
                    pressure2      REAL,                  -- pressure sensor 2
                    pid_out        REAL,                  -- PID controller output
                    demanded_rpm   REAL,                  -- demanded motor RPM
                    cmd_rpm        REAL,                  -- commanded RPM sent to drive
                    command        TEXT,                  -- textual representation of current command
                    remarks        TEXT                   -- optional notes or event flags
                );
    """)
    conn.close()


def db_writer(dq:queue.Queue, stop_e: threading.Event, db):
    logging.info("DB_Writer Thread starting...")
    conn = None
    try:
        conn = sqlite3.connect(db, timeout=10, isolation_level=None)  # autocommit mode
        cur = conn.cursor()

        cur.execute("PRAGMA journal_mode=WAL;")

        while not stop_e.is_set() or not dq.empty():
            try:
                item = dq.get(timeout=5)
            except queue.Empty:
                continue
            try:
                flow_data = item.get('flow_data')
                insert_sql = """
                             INSERT INTO kiln_data (timestamp, q_value, q_avg, temp, pressure1, pressure2, pid_out,
                                                    demanded_rpm, cmd_rpm, command, remarks)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                             ON CONFLICT(timestamp) DO UPDATE SET
                                    q_value      = excluded.q_value,
                                    q_avg        = excluded.q_avg,
                                    temp         = excluded.temp,
                                    pressure1    = excluded.pressure1,
                                    pressure2    = excluded.pressure2,
                                    pid_out      = excluded.pid_out,
                                    demanded_rpm = excluded.demanded_rpm,
                                    cmd_rpm      = excluded.cmd_rpm,
                                    command      = excluded.command,
                                    remarks      = excluded.remarks;
                             """

                q_val        = getattr(flow_data, 'q', None)
                q_avg        = getattr(flow_data,'q_avg', None)
                temp         = getattr(flow_data, 't', None)
                p1           = getattr(flow_data, 'p1', None)
                p2           = getattr(flow_data, 'p2', None)
                pid_out      = item.get('pid_out')
                demanded_rpm = item.get('demanded_rpm')
                cmd_rpm      = item.get('cmd_rpm')
                command      = item.get('cmd')
                remarks      = item.get('remarks', "")
                ts           = item.get('timestamp')
                cur.execute(insert_sql, (ts, q_val, q_avg, temp, p1, p2, pid_out,
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

    logging.info("DB_Writer Thread exit.")


if __name__ == "__main__":
    #create_data_tables("../data/data.db")
    pass