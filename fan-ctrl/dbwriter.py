import queue
import threading
import logging
import time
import sqlite3


def create_error_log_table(db):
    conn = sqlite3.connect(db, timeout=10, isolation_level=None)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS error_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            code      INTEGER DEFAULT 0,
            source    TEXT    DEFAULT '',
            message   TEXT    DEFAULT ''
        )
    """)
    conn.close()


def log_error(db, code: int, source: str, message: str):
    """Insert one error record into error_log. Safe to call from any thread."""
    try:
        conn = sqlite3.connect(db, timeout=5, isolation_level=None)
        conn.execute(
            "INSERT INTO error_log (code, source, message) VALUES (?, ?, ?)",
            (int(code), str(source), str(message))
        )
        conn.close()
    except Exception:
        logging.exception("log_error: failed to write error record")


def queue_monitor(q: queue.Queue, stop_e: threading.Event, high_level: int, discard_count: int = 100):
    logging.info("Queue Monitor Thread starting...")
    while not stop_e.is_set():
        try:
            current_size = q.qsize()
            if current_size > high_level:
                logging.warning(f"Queue size exceeding high level; discarding {discard_count} oldest items.")
                for _ in range(discard_count):
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
        except Exception as exc:
            logging.error(f"Queue monitor error: {exc}")

        time.sleep(5)
    logging.error("Queue Monitor Thread exit.")


def create_data_tables(db):
    conn = sqlite3.connect(db, timeout=10, isolation_level=None)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kiln_data (
            timestamp      TEXT PRIMARY KEY,
            q_value        REAL,
            q_avg          REAL,
            temp           REAL,
            pressure1      REAL,
            pressure2      REAL,
            pid_out        REAL,
            demanded_rpm   REAL,
            cmd_rpm        REAL,
            command        TEXT,
            remarks        TEXT
        )
    """)
    conn.close()
    create_error_log_table(db)


def db_writer(dq: queue.Queue, stop_e: threading.Event, db):
    logging.info("DB_Writer Thread starting...")
    conn = None
    try:
        conn = sqlite3.connect(db, timeout=10, isolation_level=None)
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
                    INSERT INTO kiln_data
                        (timestamp, q_value, q_avg, temp, pressure1, pressure2,
                         pid_out, demanded_rpm, cmd_rpm, command, remarks)
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
                        remarks      = excluded.remarks
                """
                cur.execute(insert_sql, (
                    item.get('timestamp'),
                    getattr(flow_data, 'q', None),
                    getattr(flow_data, 'q_avg', None),
                    getattr(flow_data, 't', None),
                    getattr(flow_data, 'p1', None),
                    getattr(flow_data, 'p2', None),
                    item.get('pid_out'),
                    item.get('demanded_rpm'),
                    item.get('cmd_rpm'),
                    item.get('cmd'),
                    item.get('remarks', ''),
                ))
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
    pass
