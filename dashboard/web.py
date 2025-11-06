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
import json
import sqlite3
import datetime as dt
from dataclasses import dataclass
from typing import Any, List, Tuple, Optional, Dict

from flask import (
    Flask, request, redirect, url_for, render_template,
    flash, jsonify, make_response, abort
)

# --- Configuration -----------------------------------------------------------
DB_PATH = os.environ.get("CONFIG_DB", os.path.abspath("../config/config.db"))
APP_USER = os.environ.get("APP_USER")
APP_PASS = os.environ.get("APP_PASS")



# --- Utilities ---------------------------------------------------------------

def utc_now_ms_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Set pragmas every connection
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
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
        return  # disabled
    auth = request.authorization
    if not auth or not (auth.username == APP_USER and auth.password == APP_PASS):
        resp = make_response("Authentication required", 401)
        resp.headers['WWW-Authenticate'] = 'Basic realm="Config Admin"'
        return resp


# --- Flask App ---------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(16))


@app.before_request
def _auth_gate():
    r = require_auth()
    if r is not None:
        return r


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    with get_db() as conn:
        if q:
            rows = conn.execute(
                "SELECT * FROM config_params WHERE name LIKE ? OR description LIKE ? ORDER BY name",
                (f"%{q}%", f"%{q}%")
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM config_params ORDER BY name").fetchall()

    return render_template("web-config.html.j2", rows=rows, query=q)


@app.route("/save/<name>", methods=["POST"])
def save_one(name: str):
    raw_val = request.form.get(f"value__{name}")
    with get_db() as conn:
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
    return redirect(url_for('index'))


@app.route("/export.json")
def export_json():
    with get_db() as conn:
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
    with get_db() as conn:
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


if __name__ == "__main__":
    print(f"DB: {DB_PATH}")
    app.run(host="0.0.0.0", port=5001, debug=True)
