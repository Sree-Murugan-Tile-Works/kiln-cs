import sqlite3
import pytest
from config import init_config_db, get_param, set_param, load_config_from_db, conf_validate
from utils import AttrDict


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "config.db")
    init_config_db(path)
    return path


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def test_config_params_table_exists(db):
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM config_params").fetchone()[0]
    conn.close()
    assert count > 0


def test_all_expected_keys_present(db):
    cfg = load_config_from_db(db)
    for key in ("kp", "ki", "kd", "set_point", "cur_cmd", "scan_interval",
                "pid_max_rpm", "motor_max_rpm", "plc_fins_port"):
        assert key in cfg, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# get_param
# ---------------------------------------------------------------------------

def test_get_param_float(db):
    conn = sqlite3.connect(db)
    val = get_param(conn, "kp")
    conn.close()
    assert isinstance(val, float)
    assert val == pytest.approx(0.0)


def test_get_param_int(db):
    conn = sqlite3.connect(db)
    val = get_param(conn, "scan_interval")
    conn.close()
    assert val == 1


def test_get_param_string(db):
    conn = sqlite3.connect(db)
    val = get_param(conn, "cur_cmd")
    conn.close()
    assert val == "OFF"


def test_get_param_missing_raises(db):
    conn = sqlite3.connect(db)
    with pytest.raises(KeyError):
        get_param(conn, "nonexistent_param")
    conn.close()


# ---------------------------------------------------------------------------
# set_param
# ---------------------------------------------------------------------------

def test_set_param_updates_float(db):
    conn = sqlite3.connect(db)
    set_param(conn, "kp", "f", 1.5, "PID Proportional Gain")
    assert get_param(conn, "kp") == pytest.approx(1.5)
    conn.close()


def test_set_param_updates_int(db):
    conn = sqlite3.connect(db)
    set_param(conn, "scan_interval", "i", 5, "Controller Scan Interval")
    assert get_param(conn, "scan_interval") == 5
    conn.close()


def test_set_param_updates_string(db):
    conn = sqlite3.connect(db)
    set_param(conn, "cur_cmd", "s", "PID 43.0", "Current Command")
    assert get_param(conn, "cur_cmd") == "PID 43.0"
    conn.close()


def test_set_param_invalid_type_raises(db):
    conn = sqlite3.connect(db)
    with pytest.raises(ValueError):
        set_param(conn, "kp", "x", 1.0, "bad type")
    conn.close()


# ---------------------------------------------------------------------------
# load_config_from_db
# ---------------------------------------------------------------------------

def test_load_config_returns_attrdict(db):
    cfg = load_config_from_db(db)
    assert isinstance(cfg, AttrDict)


def test_load_config_attribute_access(db):
    cfg = load_config_from_db(db)
    assert cfg.cur_cmd == "OFF"
    assert cfg.scan_interval == 1


# ---------------------------------------------------------------------------
# conf_validate
# ---------------------------------------------------------------------------

def test_conf_validate_passes_for_valid_config(db):
    cfg = load_config_from_db(db)
    conf_validate(cfg)  # must not raise


def test_conf_validate_raises_for_inverted_pid_rpm(db):
    cfg = load_config_from_db(db)
    cfg.pid_max_rpm = 0
    cfg.pid_min_rpm = 100
    with pytest.raises(ValueError):
        conf_validate(cfg)


def test_conf_validate_raises_for_inverted_motor_rpm(db):
    cfg = load_config_from_db(db)
    cfg.motor_max_rpm = 0
    cfg.motor_min_rpm = 100
    with pytest.raises(ValueError):
        conf_validate(cfg)
