#!/usr/bin/env python3
"""
Kiln Control System — Dashboard Web Application

Run (dev):
    flask --app web run -h 0.0.0.0 -p 5001 --debug

Run (prod):
    gunicorn -w 2 -b 0.0.0.0:5001 web:app

Env vars:
    APP_USER / APP_PASS  — HTTP Basic Auth on protected routes (disabled if unset)
    FLASK_SECRET         — session secret key
    CONFIG_DB            — path to config.db  (default: ../data/config.db)
    DATA_DB              — path to data.db    (default: ../data/data.db)
"""

import os
import sqlite3
import datetime as dt
import logging
import math
import io
from typing import Any, Dict, Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import (
    Flask, request, redirect, url_for, render_template,
    flash, jsonify, make_response, abort,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CONF_DB_PATH = os.environ.get("CONFIG_DB", os.path.abspath("../data/config.db"))
DATA_DB_PATH = os.environ.get("DATA_DB", os.path.abspath("../data/data.db"))
APP_USER = os.environ.get("APP_USER")
APP_PASS = os.environ.get("APP_PASS")

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _ensure_extra_tables() -> None:
    """Create pid_presets (config.db) and error_log (data.db) when absent."""
    try:
        with get_db(CONF_DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pid_presets (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT    NOT NULL UNIQUE,
                    kp         REAL    NOT NULL,
                    ki         REAL    NOT NULL,
                    kd         REAL    NOT NULL,
                    set_point  REAL    NOT NULL,
                    created_at TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                )
            """)
    except Exception:
        log.exception("_ensure_extra_tables: failed on config.db")

    try:
        with get_db(DATA_DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS error_log (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    code      INTEGER DEFAULT 0,
                    source    TEXT    DEFAULT '',
                    message   TEXT    DEFAULT ''
                )
            """)
    except Exception:
        log.exception("_ensure_extra_tables: failed on data.db")

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def utc_now_ms_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def _ist_tz():
    return dt.timezone(dt.timedelta(hours=5, minutes=30), name="IST")


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_iso_z(s: str) -> dt.datetime:
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.replace(tzinfo=dt.timezone.utc) if d.tzinfo is None else d
    except Exception:
        return _now_utc()


def _pid_params_from_db() -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    try:
        with get_db(CONF_DB_PATH) as conn:
            for name in ("kp", "ki", "kd", "set_point"):
                row = conn.execute(
                    "SELECT type, int_value, float_value FROM config_params WHERE name=?",
                    (name,)
                ).fetchone()
                if row:
                    params[name] = row["float_value"] if row["type"] == "f" else row["int_value"]
    except Exception:
        log.exception("_pid_params_from_db failed")
    return params


def _set_float_param(conn: sqlite3.Connection, name: str, value: float) -> None:
    conn.execute(
        """UPDATE config_params
           SET float_value=?, int_value=NULL, str_value=NULL,
               last_updated=strftime('%Y-%m-%dT%H:%M:%fZ','now')
           WHERE name=? AND type='f'""",
        (float(value), name),
    )


def coerce_for_type(raw: Optional[str], typ: str) -> Dict[str, Any]:
    if typ == 'i':
        if not raw:
            raise ValueError("Integer value required")
        return {"int_value": int(raw), "float_value": None, "str_value": None}
    if typ == 'f':
        if not raw:
            raise ValueError("Float value required")
        return {"int_value": None, "float_value": float(raw), "str_value": None}
    if typ == 's':
        return {"int_value": None, "float_value": None, "str_value": "" if raw is None else str(raw)}
    raise ValueError(f"Unknown type {typ!r}")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def require_auth():
    if not (APP_USER and APP_PASS):
        return None
    auth = request.authorization
    if not auth or auth.username != APP_USER or auth.password != APP_PASS:
        resp = make_response("Authentication required", 401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="Kiln Dashboard"'
        return resp
    return None

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(16))

_PROTECTED = {
    'config_index', 'config_save_one', 'config_export_json', 'api_config',
    'api_pid_set', 'api_pid_presets_save', 'api_pid_presets_apply',
    'api_pid_presets_delete', 'api_command',
}


@app.before_request
def _auth_gate():
    if request.endpoint in _PROTECTED:
        r = require_auth()
        if r is not None:
            return r

# ---------------------------------------------------------------------------
# Live data API
# ---------------------------------------------------------------------------

@app.route("/api/live")
def api_live():
    result: Dict[str, Any] = {
        "timestamp": None,
        "p1": None, "p2": None, "temp": None,
        "q_value": None, "q_avg": None,
        "pid_out": None, "cmd_rpm": None, "demanded_rpm": None,
        "command": None,   # what the daemon last executed (from kiln_data)
        "cur_cmd": None,   # what is currently configured in config.db
        "pid": {},
        "error": None,
    }
    try:
        with get_db(DATA_DB_PATH) as conn:
            row = conn.execute(
                "SELECT * FROM kiln_data ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if row:
                for k in ("timestamp", "p1", "p2", "temp", "q_value", "q_avg",
                          "pid_out", "cmd_rpm", "demanded_rpm", "command"):
                    if k in row.keys():
                        result[k] = row[k]
    except Exception as exc:
        result["error"] = str(exc)
        log.error("api_live data read failed: %s", exc)

    result["pid"] = _pid_params_from_db()

    # Pull the currently configured command from config.db
    try:
        with get_db(CONF_DB_PATH) as conn:
            crow = conn.execute(
                "SELECT str_value FROM config_params WHERE name='cur_cmd'"
            ).fetchone()
            if crow:
                result["cur_cmd"] = crow["str_value"]
    except Exception:
        pass  # non-fatal; cur_cmd stays None

    return jsonify(result)


@app.route("/api/history")
def api_history():
    minutes = request.args.get("minutes", 60, type=int)
    minutes = max(1, min(minutes, 1440))
    cutoff = (
        (_now_utc() - dt.timedelta(minutes=minutes))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    try:
        with get_db(DATA_DB_PATH) as conn:
            rows = conn.execute(
                """SELECT timestamp, q_avg, cmd_rpm, temp, pid_out
                   FROM kiln_data WHERE timestamp >= ?
                   ORDER BY timestamp ASC""",
                (cutoff,),
            ).fetchall()
        return jsonify({"rows": [dict(r) for r in rows]})
    except Exception as exc:
        log.error("api_history failed: %s", exc)
        return jsonify({"error": str(exc), "rows": []}), 500

# ---------------------------------------------------------------------------
# PID API
# ---------------------------------------------------------------------------

@app.route("/api/pid", methods=["GET"])
def api_pid_get():
    return jsonify(_pid_params_from_db())


@app.route("/api/pid", methods=["POST"])
def api_pid_set():
    data = request.get_json(silent=True) or {}
    errors = []
    updated: Dict[str, float] = {}
    try:
        with get_db(CONF_DB_PATH) as conn:
            for key in ("kp", "ki", "kd", "set_point"):
                if key in data:
                    try:
                        val = float(data[key])
                        _set_float_param(conn, key, val)
                        updated[key] = val
                    except (ValueError, TypeError) as exc:
                        errors.append(f"{key}: {exc}")
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    return jsonify({"ok": True, "updated": updated})

# ---------------------------------------------------------------------------
# PID Presets API
# ---------------------------------------------------------------------------

@app.route("/api/pid/presets", methods=["GET"])
def api_pid_presets_list():
    try:
        with get_db(CONF_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT id, name, kp, ki, kd, set_point, created_at FROM pid_presets ORDER BY name"
            ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/pid/presets", methods=["POST"])
def api_pid_presets_save():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    try:
        kp = float(data["kp"])
        ki = float(data["ki"])
        kd = float(data["kd"])
        sp = float(data["set_point"])
    except (KeyError, ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": f"Invalid value: {exc}"}), 400

    try:
        with get_db(CONF_DB_PATH) as conn:
            conn.execute(
                """INSERT INTO pid_presets (name, kp, ki, kd, set_point) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       kp=excluded.kp, ki=excluded.ki, kd=excluded.kd,
                       set_point=excluded.set_point,
                       created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",
                (name, kp, ki, kd, sp),
            )
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/pid/presets/<int:preset_id>/apply", methods=["POST"])
def api_pid_presets_apply(preset_id: int):
    try:
        with get_db(CONF_DB_PATH) as conn:
            row = conn.execute(
                "SELECT kp, ki, kd, set_point FROM pid_presets WHERE id=?", (preset_id,)
            ).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "Preset not found"}), 404
            for key in ("kp", "ki", "kd", "set_point"):
                _set_float_param(conn, key, row[key])
        return jsonify({"ok": True, "applied": dict(row)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/pid/presets/<int:preset_id>", methods=["DELETE"])
def api_pid_presets_delete(preset_id: int):
    try:
        with get_db(CONF_DB_PATH) as conn:
            conn.execute("DELETE FROM pid_presets WHERE id=?", (preset_id,))
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

# ---------------------------------------------------------------------------
# Error log API
# ---------------------------------------------------------------------------

@app.route("/api/errors")
def api_errors():
    limit = request.args.get("limit", 50, type=int)
    limit = max(1, min(limit, 500))
    try:
        with get_db(DATA_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT id, timestamp, code, source, message FROM error_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as exc:
        return jsonify({"error": str(exc), "rows": []}), 500

# ---------------------------------------------------------------------------
# Command API
# ---------------------------------------------------------------------------

@app.route("/api/command", methods=["POST"])
def api_command():
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode", "OFF")).upper().strip()

    if mode == "PID":
        try:
            sp = float(data["set_point"])
        except (KeyError, ValueError, TypeError):
            return jsonify({"ok": False, "error": "set_point required for PID mode"}), 400
        cmd_str = f"PID {sp}"
    elif mode == "MAN":
        try:
            rpm = int(data["rpm"])
        except (KeyError, ValueError, TypeError):
            return jsonify({"ok": False, "error": "rpm required for MAN mode"}), 400
        cmd_str = f"MAN {rpm}"
    elif mode == "OFF":
        cmd_str = "OFF"
    else:
        return jsonify({"ok": False, "error": f"Unknown mode: {mode!r}"}), 400

    try:
        with get_db(CONF_DB_PATH) as conn:
            cur = conn.execute(
                """UPDATE config_params
                   SET str_value=?, int_value=NULL, float_value=NULL,
                       last_updated=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                   WHERE name='cur_cmd' AND type='s'""",
                (cmd_str,),
            )
            if cur.rowcount == 0:
                return jsonify({
                    "ok": False,
                    "error": "cur_cmd row not found in config.db — run fan-ctrl/config.py first"
                }), 400
        return jsonify({"ok": True, "cmd": cmd_str})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------

@app.route("/dashboard")
def dashboard():
    return render_template("kiln_dashboard.html")


@app.route("/")
def index():
    return redirect(url_for("dashboard"))

# ---------------------------------------------------------------------------
# Legacy config admin routes (unchanged)
# ---------------------------------------------------------------------------

@app.route("/config")
def config_index():
    q = request.args.get("q", "").strip()
    with get_db(CONF_DB_PATH) as conn:
        if q:
            rows = conn.execute(
                "SELECT * FROM config_params WHERE name LIKE ? OR description LIKE ? ORDER BY name",
                (f"%{q}%", f"%{q}%"),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM config_params ORDER BY name").fetchall()
    return render_template("web-config.html.j2", rows=rows, query=q)


@app.route("/config/save/<name>", methods=["POST"])
def config_save_one(name: str):
    raw_val = request.form.get(f"value__{name}")
    with get_db(CONF_DB_PATH) as conn:
        row = conn.execute("SELECT type FROM config_params WHERE name=?", (name,)).fetchone()
        if not row:
            abort(404)
        try:
            cols = coerce_for_type(raw_val, row["type"])
            cols["last_updated"] = utc_now_ms_iso()
            set_clause = ",".join(f"{k}=?" for k in cols)
            with conn:
                conn.execute(
                    f"UPDATE config_params SET {set_clause} WHERE name=?",
                    list(cols.values()) + [name],
                )
            flash(f"Saved {name}.", "ok")
        except Exception as e:
            flash(f"{name}: {e}", "error")
    return redirect(url_for("config_index"))


@app.route("/config/export.json")
def config_export_json():
    with get_db(CONF_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT name,type,int_value,float_value,str_value,description,last_updated "
            "FROM config_params ORDER BY name"
        ).fetchall()
    data = {}
    for r in rows:
        val = r["int_value"] if r["type"] == 'i' else (r["float_value"] if r["type"] == 'f' else r["str_value"])
        data[r["name"]] = {"type": r["type"], "value": val,
                           "description": r["description"], "last_updated": r["last_updated"]}
    return jsonify(data)


@app.route("/api/config")
def api_config():
    with get_db(CONF_DB_PATH) as conn:
        rows = conn.execute("SELECT name,type,int_value,float_value,str_value FROM config_params").fetchall()
    out = {}
    for r in rows:
        out[r["name"]] = r["int_value"] if r["type"] == 'i' else (r["float_value"] if r["type"] == 'f' else r["str_value"])
    return jsonify(out)


@app.route("/dashboard/graph")
def graph_png():
    t_end = _now_utc()
    t_start = t_end - dt.timedelta(hours=1)
    t_start_iso = t_start.isoformat(timespec="seconds").replace("+00:00", "Z")
    rows = []
    with get_db(DATA_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT * FROM kiln_data WHERE timestamp >= ? ORDER BY timestamp ASC",
            (t_start_iso,),
        ).fetchall()

    xs, q_avg_vals, cmd_rpm_vals = [], [], []
    have_q = have_r = False
    for r in rows:
        try:
            xs.append(_parse_iso_z(r["timestamp"]))
        except Exception:
            continue
        if "q_avg" in r.keys():
            q_avg_vals.append(r["q_avg"]); have_q = True
        else:
            q_avg_vals.append(math.nan)
        if "cmd_rpm" in r.keys():
            cmd_rpm_vals.append(r["cmd_rpm"]); have_r = True
        else:
            cmd_rpm_vals.append(math.nan)

    fig, ax = plt.subplots(figsize=(8, 3), dpi=120)
    if xs:
        if have_q:
            ax.plot(xs, q_avg_vals, label="q_avg")
        if have_r:
            ax.plot(xs, cmd_rpm_vals, label="cmd_rpm")
        ax.set_xlabel("Time (UTC)")
        ax.set_xlim([t_start, t_end])
        ax.grid(True, alpha=0.3)
        if have_q or have_r:
            ax.legend()
    else:
        ax.text(0.5, 0.5, "No data in last hour", ha="center", va="center", transform=ax.transAxes)
        ax.axis("off")

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    resp = make_response(buf.read())
    resp.headers["Content-Type"] = "image/png"
    resp.headers["Cache-Control"] = "max-age=15, public"
    return resp

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

with app.app_context():
    _ensure_extra_tables()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=5001, debug=True)
