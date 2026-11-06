import datetime as dt
import sqlite3

import pytest

import web
from dbwriter import log_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _recent_iso(minutes_ago: int = 5) -> str:
    return (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _insert_kiln_row(data_db: str, **overrides):
    defaults = {
        "timestamp": _recent_iso(),
        "q_value": 42.0, "q_avg": 41.5, "temp": 150.0,
        "pressure1": 130.0, "pressure2": 100.0,
        "pid_out": 0.65, "demanded_rpm": 300.0, "cmd_rpm": 300.0,
        "command": "PID", "remarks": "",
    }
    defaults.update(overrides)
    conn = sqlite3.connect(data_db)
    conn.execute(
        """INSERT INTO kiln_data
           (timestamp, q_value, q_avg, temp, pressure1, pressure2,
            pid_out, demanded_rpm, cmd_rpm, command, remarks)
           VALUES (:timestamp, :q_value, :q_avg, :temp, :pressure1, :pressure2,
                   :pid_out, :demanded_rpm, :cmd_rpm, :command, :remarks)""",
        defaults,
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# GET /api/live
# ---------------------------------------------------------------------------

def test_live_empty_db_returns_nulls(app_ctx):
    r = app_ctx.client.get("/api/live")
    assert r.status_code == 200
    d = r.get_json()
    assert d["timestamp"] is None
    assert d["temp"] is None
    assert d["q_avg"] is None


def test_live_with_data_returns_row(app_ctx):
    _insert_kiln_row(app_ctx.data_db, temp=175.0, q_avg=55.0)
    r = app_ctx.client.get("/api/live")
    assert r.status_code == 200
    d = r.get_json()
    assert d["timestamp"] is not None
    assert d["temp"] == pytest.approx(175.0)
    assert d["q_avg"] == pytest.approx(55.0)


def test_live_includes_cur_cmd_from_config(app_ctx):
    r = app_ctx.client.get("/api/live")
    d = r.get_json()
    assert d["cur_cmd"] == "OFF"    # default seeded by init_config_db


def test_live_includes_pid_params(app_ctx):
    r = app_ctx.client.get("/api/live")
    d = r.get_json()
    assert "pid" in d
    assert "kp" in d["pid"]


# ---------------------------------------------------------------------------
# GET /api/history
# ---------------------------------------------------------------------------

def test_history_empty_db(app_ctx):
    r = app_ctx.client.get("/api/history")
    assert r.status_code == 200
    assert r.get_json()["rows"] == []


def test_history_returns_recent_rows(app_ctx):
    _insert_kiln_row(app_ctx.data_db, timestamp=_recent_iso(2), temp=160.0)
    r = app_ctx.client.get("/api/history?minutes=60")
    assert r.status_code == 200
    rows = r.get_json()["rows"]
    assert len(rows) == 1
    assert rows[0]["temp"] == pytest.approx(160.0)


def test_history_minutes_clamped_high(app_ctx):
    r = app_ctx.client.get("/api/history?minutes=99999")
    assert r.status_code == 200   # clamped to 1440, not an error


def test_history_minutes_clamped_low(app_ctx):
    r = app_ctx.client.get("/api/history?minutes=0")
    assert r.status_code == 200   # clamped to 1, not an error


# ---------------------------------------------------------------------------
# GET /api/pid  &  POST /api/pid
# ---------------------------------------------------------------------------

def test_pid_get_returns_defaults(app_ctx):
    r = app_ctx.client.get("/api/pid")
    assert r.status_code == 200
    d = r.get_json()
    assert "kp" in d
    assert d["kp"] == pytest.approx(0.0)   # default seeded value


def test_pid_post_valid_updates_values(app_ctx):
    payload = {"kp": 1.2, "ki": 0.05, "kd": 0.01, "set_point": 43.0}
    r = app_ctx.client.post("/api/pid", json=payload)
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    # Verify persistence
    d = app_ctx.client.get("/api/pid").get_json()
    assert d["kp"] == pytest.approx(1.2)
    assert d["set_point"] == pytest.approx(43.0)


def test_pid_post_partial_update(app_ctx):
    app_ctx.client.post("/api/pid", json={"kp": 2.0, "ki": 0.1, "kd": 0.05, "set_point": 40.0})
    r = app_ctx.client.post("/api/pid", json={"kp": 3.0})   # only kp
    assert r.status_code == 200
    d = app_ctx.client.get("/api/pid").get_json()
    assert d["kp"] == pytest.approx(3.0)
    assert d["ki"] == pytest.approx(0.1)   # unchanged


def test_pid_post_invalid_value_returns_400(app_ctx):
    r = app_ctx.client.post("/api/pid", json={"kp": "not_a_number"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# PID Presets CRUD
# ---------------------------------------------------------------------------

def _preset_payload(**overrides):
    p = {"name": "base", "kp": 1.0, "ki": 0.1, "kd": 0.05, "set_point": 40.0}
    p.update(overrides)
    return p


def test_presets_initially_empty(app_ctx):
    r = app_ctx.client.get("/api/pid/presets")
    assert r.status_code == 200
    assert r.get_json() == []


def test_presets_save_and_list(app_ctx):
    r = app_ctx.client.post("/api/pid/presets", json=_preset_payload(name="p1"))
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    presets = app_ctx.client.get("/api/pid/presets").get_json()
    assert len(presets) == 1
    assert presets[0]["name"] == "p1"
    assert presets[0]["kp"] == pytest.approx(1.0)


def test_presets_upsert_on_duplicate_name(app_ctx):
    app_ctx.client.post("/api/pid/presets", json=_preset_payload(name="dup", kp=1.0))
    app_ctx.client.post("/api/pid/presets", json=_preset_payload(name="dup", kp=2.0))
    presets = app_ctx.client.get("/api/pid/presets").get_json()
    assert len(presets) == 1
    assert presets[0]["kp"] == pytest.approx(2.0)


def test_presets_apply_loads_values_into_config(app_ctx):
    app_ctx.client.post("/api/pid/presets", json=_preset_payload(name="apply-me", kp=5.0, set_point=99.0))
    pid_id = app_ctx.client.get("/api/pid/presets").get_json()[0]["id"]

    r = app_ctx.client.post(f"/api/pid/presets/{pid_id}/apply")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["applied"]["kp"] == pytest.approx(5.0)

    pid = app_ctx.client.get("/api/pid").get_json()
    assert pid["kp"] == pytest.approx(5.0)
    assert pid["set_point"] == pytest.approx(99.0)


def test_presets_apply_not_found_returns_404(app_ctx):
    r = app_ctx.client.post("/api/pid/presets/9999/apply")
    assert r.status_code == 404


def test_presets_delete(app_ctx):
    app_ctx.client.post("/api/pid/presets", json=_preset_payload(name="del-me"))
    pid_id = app_ctx.client.get("/api/pid/presets").get_json()[0]["id"]

    r = app_ctx.client.delete(f"/api/pid/presets/{pid_id}")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert app_ctx.client.get("/api/pid/presets").get_json() == []


def test_presets_save_missing_name_returns_400(app_ctx):
    r = app_ctx.client.post("/api/pid/presets",
                            json={"kp": 1.0, "ki": 0.1, "kd": 0.05, "set_point": 40.0})
    assert r.status_code == 400


def test_presets_save_invalid_value_returns_400(app_ctx):
    r = app_ctx.client.post("/api/pid/presets",
                            json={"name": "bad", "kp": "x", "ki": 0.1, "kd": 0.05, "set_point": 40.0})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/errors
# ---------------------------------------------------------------------------

def test_errors_empty(app_ctx):
    r = app_ctx.client.get("/api/errors")
    assert r.status_code == 200
    assert r.get_json() == []


def test_errors_returns_logged_entries(app_ctx):
    log_error(app_ctx.data_db, code=1, source="plc", message="timeout")
    r = app_ctx.client.get("/api/errors?limit=10")
    assert r.status_code == 200
    rows = r.get_json()
    assert len(rows) == 1
    assert rows[0]["source"] == "plc"
    assert rows[0]["message"] == "timeout"
    assert rows[0]["code"] == 1


def test_errors_limit_respected(app_ctx):
    for i in range(5):
        log_error(app_ctx.data_db, code=i, source="s", message=f"err {i}")
    r = app_ctx.client.get("/api/errors?limit=3")
    assert r.status_code == 200
    assert len(r.get_json()) == 3


# ---------------------------------------------------------------------------
# POST /api/command
# ---------------------------------------------------------------------------

def test_command_off(app_ctx):
    r = app_ctx.client.post("/api/command", json={"mode": "OFF"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["cmd"] == "OFF"


def test_command_pid(app_ctx):
    r = app_ctx.client.post("/api/command", json={"mode": "PID", "set_point": 43.5})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["cmd"] == "PID 43.5"


def test_command_man(app_ctx):
    r = app_ctx.client.post("/api/command", json={"mode": "MAN", "rpm": 300})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["cmd"] == "MAN 300"


def test_command_pid_missing_set_point_returns_400(app_ctx):
    r = app_ctx.client.post("/api/command", json={"mode": "PID"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_command_man_missing_rpm_returns_400(app_ctx):
    r = app_ctx.client.post("/api/command", json={"mode": "MAN"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_command_unknown_mode_returns_400(app_ctx):
    r = app_ctx.client.post("/api/command", json={"mode": "TURBO"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_command_persists_to_config_db(app_ctx):
    app_ctx.client.post("/api/command", json={"mode": "MAN", "rpm": 200})
    conn = sqlite3.connect(app_ctx.conf_db)
    row = conn.execute("SELECT str_value FROM config_params WHERE name='cur_cmd'").fetchone()
    conn.close()
    assert row[0] == "MAN 200"


def test_command_missing_cur_cmd_row_returns_400(app_ctx):
    conn = sqlite3.connect(app_ctx.conf_db)
    conn.execute("DELETE FROM config_params WHERE name='cur_cmd'")
    conn.commit()
    conn.close()
    r = app_ctx.client.post("/api/command", json={"mode": "OFF"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


# ---------------------------------------------------------------------------
# Dashboard route & redirect
# ---------------------------------------------------------------------------

def test_dashboard_returns_200(app_ctx):
    r = app_ctx.client.get("/dashboard")
    assert r.status_code == 200
    assert b"kiln" in r.data.lower()


def test_root_redirects_to_dashboard(app_ctx):
    r = app_ctx.client.get("/")
    assert r.status_code == 302
    assert "/dashboard" in r.headers["Location"]


# ---------------------------------------------------------------------------
# coerce_for_type utility
# ---------------------------------------------------------------------------

def test_coerce_int():
    assert web.coerce_for_type("42", "i") == {"int_value": 42, "float_value": None, "str_value": None}


def test_coerce_float():
    result = web.coerce_for_type("3.14", "f")
    assert result["float_value"] == pytest.approx(3.14)
    assert result["int_value"] is None
    assert result["str_value"] is None


def test_coerce_str():
    assert web.coerce_for_type("hello", "s") == {"int_value": None, "float_value": None, "str_value": "hello"}


def test_coerce_str_none_becomes_empty():
    assert web.coerce_for_type(None, "s")["str_value"] == ""


def test_coerce_empty_int_raises():
    with pytest.raises(ValueError):
        web.coerce_for_type("", "i")


def test_coerce_empty_float_raises():
    with pytest.raises(ValueError):
        web.coerce_for_type("", "f")


def test_coerce_unknown_type_raises():
    with pytest.raises(ValueError):
        web.coerce_for_type("x", "z")
