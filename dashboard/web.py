#!/usr/bin/env python3
"""

Run (dev):
    export FLASK_APP=config_admin.py
    flask --app config_admin run -h 0.0.0.0 -p 5001 --debug

Run (prod):
    pip install gunicorn
    gunicorn -w 2 -b 0.0.0.0:5001 config_admin:app

"""

import os
import sqlite3
import datetime as dt
from typing import Any, List, Tuple, Optional, Dict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import io
import math
from flask import (
    Flask, request, redirect, url_for, render_template,
    flash, jsonify, make_response, abort
)

# --- Configuration -----------------------------------------------------------
CONF_DB_PATH = os.environ.get("CONFIG_DB", os.path.abspath("../data/config.db"))
DATA_DB_PATH = os.environ.get("DATA_DB", os.path.abspath("../data/data.db"))
APP_USER = os.environ.get("APP_USER")
APP_PASS = os.environ.get("APP_PASS")


# --- Utilities ---------------------------------------------------------------

def utc_now_ms_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def _ist_tz():
    # Asia/Kolkata offset (+05:30) without external deps
    return dt.timezone(dt.timedelta(hours=5, minutes=30), name="IST")


def _now_utc():
    return dt.datetime.now(dt.timezone.utc)


def _one_hour_ago_utc():
    return _now_utc() - dt.timedelta(hours=1)


def _parse_iso_z(s: str) -> dt.datetime:
    # Accept ISO-8601 strings (with or without 'Z'); default to UTC
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d
    except Exception:
        return _now_utc()  # fallback; don't crash page


def get_db(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Set pragmas every connection
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def coerce_for_type(raw: Optional[str], typ: str) -> Dict[str, Any]:
    """Return a dict of column->value ensuring only the correct column is non-NULL.
    Raises ValueError on type conversion errors.
    """
    if typ == 'i':
        if raw is None or raw == "":
            raise ValueError("Integer value required")
        v = int(raw)
        return {"int_value": v, "float_value": None, "str_value": None}
    elif typ == 'f':
        if raw is None or raw == "":
            raise ValueError("Float value required")
        v = float(raw)
        return {"int_value": None, "float_value": v, "str_value": None}
    elif typ == 's':
        # Allow empty string as valid value
        print(raw, type(raw))
        v = "" if raw is None else str(raw)
        return {"int_value": None, "float_value": None, "str_value": v}
    else:
        raise ValueError(f"Unknown type {typ}")


# --- Basic HTTP Auth ---------------------------------------------------------

def require_auth():
    if not (APP_USER and APP_PASS):
        return  None # disabled
    auth = request.authorization
    if not auth or not (auth.username == APP_USER and auth.password == APP_PASS):
        resp = make_response("Authentication required", 401)
        resp.headers['WWW-Authenticate'] = 'Basic realm="Config Admin"'
        return resp
    return None

# --- Flask App ---------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(16))


PROTECTED_ENDPOINTS = { 'config_index', 'config_save_one', 'config_export_json', 'api_config'}


@app.before_request
def _auth_gate():
    if request.endpoint in PROTECTED_ENDPOINTS:
        r = require_auth()
        if r is not None:
            return r
    return None

@app.route("/config")
def config_index():
    q = request.args.get("q", "").strip()
    with get_db(CONF_DB_PATH) as conn:
        if q:
            rows = conn.execute(
                "SELECT * FROM config_params WHERE name LIKE ? OR description LIKE ? ORDER BY name",
                (f"%{q}%", f"%{q}%")
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
        typ = row["type"]
        try:
            cols = coerce_for_type(raw_val, typ)
            cols["last_updated"] = utc_now_ms_iso()
            set_clause = ",".join(f"{k}=?" for k in cols.keys())
            params = list(cols.values()) + [name]
            with conn:
                sql = f"UPDATE config_params SET {set_clause} WHERE name=?"
                print(sql, params)
                conn.execute(sql, params)
            flash(f"Saved {name}.", "ok")
        except Exception as e:
            flash(f"{name}: {e}", "error")
    return redirect(url_for('config_index'))


@app.route("/config/export.json")
def config_export_json():
    with get_db(CONF_DB_PATH) as conn:
        rows = conn.execute("SELECT name,type,int_value,float_value,str_value,description,last_updated FROM config_params ORDER BY name").fetchall()
    data = {}
    for r in rows:
        if r["type"] == 'i':
            val = r["int_value"]
        elif r["type"] == 'f':
            val = r["float_value"]
        else:
            val = r["str_value"]
        data[r["name"]] = {
            "type": r["type"],
            "value": val,
            "description": r["description"],
            "last_updated": r["last_updated"],
        }
    return jsonify(data)


@app.route("/api/config")
def api_config():
    """Return a flat name->value mapping, convenient for your services."""
    with get_db(CONF_DB_PATH) as conn:
        rows = conn.execute("SELECT name,type,int_value,float_value,str_value FROM config_params").fetchall()
    out = {}
    for r in rows:
        if r["type"] == 'i':
            out[r["name"]] = r["int_value"]
        elif r["type"] == 'f':
            out[r["name"]] = r["float_value"]
        else:
            out[r["name"]] = r["str_value"]
    return jsonify(out)


@app.route("/dashboard")
def dashboard():
    # Attempt to read the latest row from a table named 'kiln_data' with a TEXT ISO timestamp column 'timestamp'
    latest = None
    with get_db(DATA_DB_PATH) as conn:
        latest = conn.execute(
            """
            SELECT *
            FROM kiln_data
            ORDER BY timestamp DESC
            LIMIT 1
            """
        ).fetchone()

    # Prepare a dict of "current readings" with friendly keys
    current = {}
    timestamp_ist = None
    if latest:
        # Map likely columns; tolerate missing ones
        # Common schema you shared earlier: timestamp (TEXT ISO-8601), q_avg, cmd_rpm, temp, pressure1, pressure2, pid_out, demanded_rpm, command
        cols_of_interest = [
            "q_value", "q_avg", "temp", "pressure1", "pressure2",
            "pid_out", "demanded_rpm", "cmd_rpm", "command", "set_value"
        ]
        for k in cols_of_interest:
            if k in latest.keys():
                current[k] = latest[k]
        # Handle timestamp display in IST
        if "timestamp" in latest.keys() and latest["timestamp"]:
            try:
                timestamp_ist = _parse_iso_z(latest["timestamp"]).astimezone(_ist_tz()).isoformat(timespec="seconds")
            except Exception:
                timestamp_ist = latest["timestamp"]

    return render_template("web-dashboard.html.j2",
                           current=current,
                           timestamp_ist=timestamp_ist)

@app.route("/dashboard/graph")
def graph_png():
    t_end = _now_utc()
    t_start = _one_hour_ago_utc()
    t_start_iso = t_start.isoformat(timespec="seconds").replace("+00:00", "Z")
    # Pull last 60 mins; tolerate missing columns
    rows = []
    have_qavg = have_cmdrpm = False
    with get_db(DATA_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM kiln_data
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (t_start_iso,)
        ).fetchall()

    xs = []
    q_avg = []
    cmd_rpm = []

    for r in rows or []:
        ts = r.get("timestamp") if isinstance(r, dict) else r["timestamp"]
        try:
            ts = _parse_iso_z(ts)
        except Exception:
            continue
        xs.append(ts)

        if "q_avg" in r.keys():
            q_avg.append(r["q_avg"])
            have_qavg = True
        else:
            q_avg.append(math.nan)

        if "cmd_rpm" in r.keys():
            cmd_rpm.append(r["cmd_rpm"])
            have_cmdrpm = True
        else:
            cmd_rpm.append(math.nan)

    # Build the PNG
    fig, ax = plt.subplots(figsize=(8, 3), dpi=120)
    if xs:
        if have_qavg:
            ax.plot(xs, q_avg, label="q_avg")
        if have_cmdrpm:
            ax.plot(xs, cmd_rpm, label="cmd_rpm")
        ax.set_xlabel("Time (UTC)")
        ax.set_xlim([t_start, t_end])
        ax.grid(True, alpha=0.3)
        if have_qavg or have_cmdrpm:
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


@app.route("/")
def index():
    return redirect(url_for('dashboard'))


if __name__ == "__main__":
    print(f"DB: {CONF_DB_PATH}")
    app.run(host="0.0.0.0", port=5001, debug=True)
