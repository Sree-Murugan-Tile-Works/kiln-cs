"""
Shared fixtures for dashboard tests.

pytest.ini adds both fan-ctrl/ and dashboard/ to sys.path, so:
  - `import web`           resolves to dashboard/web.py
  - `import config`        resolves to fan-ctrl/config.py
  - `import dbwriter`      resolves to fan-ctrl/dbwriter.py
"""
from types import SimpleNamespace

import pytest

import web
import config as fan_cfg
from dbwriter import create_data_tables


@pytest.fixture()
def app_ctx(tmp_path, monkeypatch):
    """
    Yields a SimpleNamespace(client, conf_db, data_db).

    Sets up isolated SQLite databases in tmp_path, seeds config.db with
    fan-ctrl defaults, and patches web.py's module-level DB path constants
    so every route in the test hits the tmp databases.
    """
    conf_db = str(tmp_path / "config.db")
    data_db = str(tmp_path / "data.db")

    # Seed databases before patching so the helpers use explicit paths (not globals)
    fan_cfg.init_config_db(conf_db)
    create_data_tables(data_db)

    # Redirect web.py to the tmp databases
    monkeypatch.setattr(web, "CONF_DB_PATH", conf_db)
    monkeypatch.setattr(web, "DATA_DB_PATH", data_db)

    # Disable HTTP Basic Auth for all tests
    monkeypatch.setattr(web, "APP_USER", None)
    monkeypatch.setattr(web, "APP_PASS", None)

    # Create dashboard-owned tables (pid_presets in conf_db, error_log already in data_db)
    with web.app.app_context():
        web._ensure_extra_tables()

    web.app.testing = True
    client = web.app.test_client()

    return SimpleNamespace(client=client, conf_db=conf_db, data_db=data_db)
