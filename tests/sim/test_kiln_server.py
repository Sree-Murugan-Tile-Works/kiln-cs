"""Routes of the kiln page (build stage I). Pattern as ``test_server.py``: no background thread."""
import time

import pytest

from sim.kiln_runner import KILN_SPEEDS, KILN_DT_S
from sim.server import create_app


@pytest.fixture()
def client():
    app = create_app(autostart=False)
    yield app.test_client(), app.config["KILN_RUNNER"]
    app.config["RUNNER"].stop()
    app.config["KILN_RUNNER"].stop()


def test_pages_link_to_each_other(client):
    c, _ = client
    kiln = c.get("/kiln")
    assert kiln.status_code == 200
    assert b'id="ring"' in kiln.data and b'id="profile"' in kiln.data and b'id="dampers"' in kiln.data
    assert b'href="/"' in kiln.data and b"placeholder" in kiln.data
    assert b'href="/kiln"' in c.get("/").data
    assert c.get("/static/kiln.js").status_code == 200


def test_state_has_records_and_every_unit(client):
    c, kiln = client
    kiln.advance(5)
    data = c.get("/api/kiln/state").get_json()
    assert data["dt_s"] == KILN_DT_S and len(data["records"]) == 6           # one step taken at start
    assert len(data["kiln"]["units"]) == 60
    unit = data["kiln"]["units"][0]
    assert {"zone", "door", "damper_lift_in", "paper_sealed", "point_c", "tile_c", "brick_c", "water_kg",
            "damper_share", "charging"} <= unit.keys()
    record = data["records"][-1]
    assert {"t_exhaust_c", "exhaust_kg_s", "rpm", "p1_pa", "p2_pa", "peak_point_c", "fuel_last_hour_kg"} <= record.keys()
    shares = sum(u["damper_share"] for u in data["kiln"]["units"])
    assert shares == pytest.approx(1.0)
    since = data["records"][3]["time_s"]
    assert len(c.get(f"/api/kiln/state?since={since}").get_json()["records"]) == 2


def test_controls_are_validated_and_applied(client):
    c, kiln = client
    ok = c.post("/api/kiln/params", json={"rpm": 450, "fuel_moisture": 0.3, "ru_per_day": 10})
    assert ok.status_code == 200
    assert kiln.sim.rpm == 450 and kiln.sim.fuel_moisture == 0.3 and kiln.sim.schedule.ru_per_day == 10
    bad = c.post("/api/kiln/params", json={"rpm": 300, "fuel_moisture": 5})
    assert bad.status_code == 400
    assert kiln.sim.rpm == 450 and kiln.controls["rpm"] == 450                # rejected change left no trace
    assert c.post("/api/kiln/params", json={"nope": 1}).status_code == 400
    assert c.post("/api/kiln/params", json={"ru_per_day": 40}).status_code == 400   # train would not fit


def test_upsets(client):
    c, kiln = client
    skip = c.post("/api/kiln/upset", json={"type": "skip", "count": 3}).get_json()
    assert len(skip["units"]) >= 15
    assert c.post("/api/kiln/upset", json={"type": "damper", "unit": 21, "lift_in": 6}).status_code == 200
    assert c.post("/api/kiln/upset", json={"type": "door", "unit": 45, "door": "open"}).status_code == 200
    kiln.advance(1)
    units = c.get("/api/kiln/state").get_json()["kiln"]["units"]
    assert units[20]["damper_lift_in"] == 6 and units[20]["damper_override"]
    assert units[44]["door"] == "open" and units[44]["door_override"]
    assert c.post("/api/kiln/upset", json={"type": "damper", "unit": 2, "lift_in": 6}).status_code == 400
    assert c.post("/api/kiln/upset", json={"type": "door", "unit": 3.5, "door": "open"}).status_code == 400
    assert c.post("/api/kiln/upset", json={"type": "flood"}).status_code == 400
    c.post("/api/kiln/upset", json={"type": "clear"})
    assert not kiln.sim.damper_overrides and not kiln.sim.door_overrides


def test_pause_speed_and_restart(client):
    c, kiln = client
    kiln.advance(4)
    reply = c.post("/api/kiln/control", json={"action": "pause", "speed": KILN_SPEEDS[-1]}).get_json()
    assert reply == {"running": False, "speed": KILN_SPEEDS[-1]}
    assert c.post("/api/kiln/control", json={"speed": 7}).status_code == 400
    assert c.post("/api/kiln/control", json={"action": "explode"}).status_code == 400
    c.post("/api/kiln/params", json={"rpm": 420})
    c.post("/api/kiln/control", json={"action": "reset"})
    state = c.get("/api/kiln/state").get_json()
    assert len(state["records"]) == 1 and state["time_s"] == KILN_DT_S
    assert kiln.sim.rpm == 420                                               # controls survive a restart


def test_exhaust_page_api_is_unchanged(client):
    c, _ = client
    assert c.get("/api/state").status_code == 200
    assert c.get("/api/specs").get_json()["channels"] == ["p1", "p2", "t"]


def test_kiln_background_thread_runs_faster_than_real_time():
    app = create_app(autostart=True)
    kiln = app.config["KILN_RUNNER"]
    try:
        deadline = time.time() + 5
        while time.time() < deadline and kiln.sim.time_s < 5 * KILN_DT_S:
            time.sleep(0.05)
        assert kiln.sim.time_s >= 5 * KILN_DT_S                              # 25 simulated minutes in seconds
    finally:
        app.config["RUNNER"].stop()
        kiln.stop()
