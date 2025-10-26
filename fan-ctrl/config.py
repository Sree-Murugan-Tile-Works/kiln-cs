import pprint
import sqlite3
from typing import Optional, Any, List, Tuple

from utils import AttrDict


parameters_definition: List[Tuple[str, str, Any, str]] = [
    ('ip', 's', None, 'PLC IP Address'),
    ('fins_port', 'i', 9600, 'PLC FINS Port'),
    ('kp', 'f', 0, 'PID Proportional Gain'),
    ('ki', 'f', 0, 'PID Integral Gain'),
    ('kd', 'f', 0, 'PID Derivative Gain'),
    ('c', 'f', 0.7, 'Orifice Plate C'),
    ('a2', 'f', 0.6096 ** 2, 'Orifice Plate A2'),
    ('z', 'f', 0.981213836, 'Orifice Plate Z'),
    ('r', 'f', 8.31445, 'Universal gas constant R'),
    ('m', 'f', 89, 'Molecular weight m'),
    ('k', 'f', 1.4, 'Specific heat ratio k'),
    ('set_point', 'f', 34.0, 'Set Point'),
    ('scan_interval', 'i', 1, 'Controller Scan Interval'),
    ('cur_cmd', 's', 'OFF', 'Current Command [PID 43.0 | MAN 340 | OFF]'),
    ('pid_max_rpm', 'i', 450, 'PID Max Output RPM'),
    ('pid_min_rpm', 'i', 0, 'PID Min Output RPM'),
]


def create_config_db(db_path):

    # create db, table and populate

    SCHEMA = """
    PRAGMA journal_mode=WAL;
    PRAGMA foreign_keys=ON;
    
    CREATE TABLE IF NOT EXISTS config_params (
        name       TEXT PRIMARY KEY,
        type       CHAR(1) NOT NULL CHECK (type IN ('i','f','s')),
        int_value  INTEGER,
        float_value REAL,
        str_value  TEXT,
        description TEXT,
        last_updated TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        -- exactly one value column must be non-NULL, matching `type`
        CHECK (
            (type='i' AND int_value  IS NOT NULL AND float_value IS NULL AND str_value IS NULL) OR
            (type='f' AND float_value IS NOT NULL AND int_value  IS NULL AND str_value IS NULL) OR
            (type='s' AND str_value  IS NOT NULL AND int_value  IS NULL AND float_value IS NULL)
        )
    );
    """
    conn = sqlite3.connect(str(db_path))
    with conn:
        conn.executescript(SCHEMA)
    return conn


def set_param(conn: sqlite3.Connection, name: str, type_char: str, value: Any, desc: str) -> None:
    type_char = type_char.lower()
    if type_char not in ('i','f','s'):
        raise ValueError("type_char must be one of: 'i','f','s'")
    # cast to the declared type
    int_value = float_value = str_value = None
    if type_char == 'i':
        int_value = int(value)
    elif type_char == 'f':
        float_value = float(value)
    else:
        str_value = str(value)

    with conn:
        conn.execute(
            """
            INSERT INTO config_params (name, type, int_value, float_value, str_value, description, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)  
                ON CONFLICT(name) DO UPDATE SET
                type         = excluded.type,
                int_value    = excluded.int_value,
                float_value  = excluded.float_value,
                str_value    = excluded.str_value,
                description  = excluded.description,
                last_updated = strftime('%Y-%m-%dT%H:%M:%fZ','now');
            """,
            (name, type_char, int_value, float_value, str_value, desc)
        )


def init_config_db(db_path):
    db = create_config_db(db_path)
    for p in parameters_definition:
      set_param(db, p[0], p[1], p[2], p[3])


def get_param(conn: sqlite3.Connection, name: str) -> Any:
    row = conn.execute("SELECT type, int_value, float_value, str_value FROM config_params WHERE name=?", (name,)).fetchone()
    if not row:
        raise KeyError(f"Parameter not found: {name}")
    t, i_v, f_v, s_v = row
    if t == 'i':
        return i_v
    if t == 'f':
        return f_v
    return s_v  # 's'



def load_config_from_db(db_path):
    config = AttrDict()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # enables name-based column access

    try:
        cursor = conn.execute("SELECT name, type, int_value, float_value, str_value FROM config_params")
        for row in cursor.fetchall():
            type_char = row["type"]
            if type_char == "i":
                value: Any = row["int_value"]
            elif type_char == "f":
                value = row["float_value"]
            else:
                value = row["str_value"]

            config[row["name"]] = value

    finally:
        conn.close()

    return config


if __name__ == '__main__':
    db = "../data/config.db"
    init_config_db(db)
    cfg = load_config_from_db(db)
    pprint.pp(cfg)

