import queue
import threading
import logging
import time


def queue_monitor(q: queue.Queue, stop_e: threading.Event, high_level: int, discard_count: int = 100):

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


def db_writer(dq:queue.Queue, stop_e: threading.Event):
    pass