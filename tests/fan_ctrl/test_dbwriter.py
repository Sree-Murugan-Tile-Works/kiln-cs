import queue
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from dbwriter import create_data_tables, create_error_log_table, log_error, db_writer


@pytest.fixture()
def data_db(tmp_path):
    path = str(tmp_path / "data.db")
    create_data_tables(path)
    return path


# ---------------------------------------------------------------------------
# create_data_tables
# ---------------------------------------------------------------------------

def test_kiln_data_table_created(data_db):
    conn = sqlite3.connect(data_db)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='kiln_data'"
    ).fetchone()
    conn.close()
    assert row is not None


def test_error_log_table_created(data_db):
    conn = sqlite3.connect(data_db)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='error_log'"
    ).fetchone()
    conn.close()
    assert row is not None


def test_create_data_tables_idempotent(tmp_path):
    path = str(tmp_path / "data.db")
    create_data_tables(path)
    create_data_tables(path)   # second call must not raise


# ---------------------------------------------------------------------------
# log_error
# ---------------------------------------------------------------------------

def test_log_error_inserts_row(data_db):
    log_error(data_db, code=42, source="plc", message="connection timeout")
    conn = sqlite3.connect(data_db)
    row = conn.execute("SELECT code, source, message FROM error_log").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 42
    assert row[1] == "plc"
    assert row[2] == "connection timeout"


def test_log_error_multiple_rows(data_db):
    log_error(data_db, code=1, source="a", message="first")
    log_error(data_db, code=2, source="b", message="second")
    conn = sqlite3.connect(data_db)
    count = conn.execute("SELECT COUNT(*) FROM error_log").fetchone()[0]
    conn.close()
    assert count == 2


# ---------------------------------------------------------------------------
# db_writer thread
# ---------------------------------------------------------------------------

def _make_item(ts="2026-01-01T00:00:00.000Z"):
    flow = SimpleNamespace(p1=100.0, p2=80.0, t=150.0, q=42.0, q_avg=41.5)
    return {
        "flow_data": flow,
        "cmd": "MAN",
        "pid_out": 0.0,
        "demanded_rpm": 300.0,
        "cmd_rpm": 300.0,
        "timestamp": ts,
    }


def test_db_writer_inserts_single_row(data_db):
    dq = queue.Queue()
    stop = threading.Event()
    dq.put(_make_item("2026-01-01T00:00:00.000Z"))

    t = threading.Thread(target=db_writer, args=(dq, stop, data_db))
    t.start()
    stop.set()          # signal stop; thread drains remaining item before exiting
    t.join(timeout=5)
    assert not t.is_alive(), "db_writer thread did not finish in time"

    conn = sqlite3.connect(data_db)
    row = conn.execute(
        "SELECT cmd_rpm, command FROM kiln_data WHERE timestamp='2026-01-01T00:00:00.000Z'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == pytest.approx(300.0)
    assert row[1] == "MAN"


def test_db_writer_inserts_multiple_rows(data_db):
    dq = queue.Queue()
    stop = threading.Event()
    for i in range(3):
        dq.put(_make_item(f"2026-01-01T00:00:0{i}.000Z"))

    t = threading.Thread(target=db_writer, args=(dq, stop, data_db))
    t.start()
    stop.set()
    t.join(timeout=5)

    conn = sqlite3.connect(data_db)
    count = conn.execute("SELECT COUNT(*) FROM kiln_data").fetchone()[0]
    conn.close()
    assert count == 3
