import pytest

from sim.server import create_app, SPEEDS


@pytest.fixture()
def client():
    app = create_app(autostart=False)       # no background thread: tests advance the simulation by hand
    yield app.test_client(), app.config["RUNNER"]
    app.config["RUNNER"].stop()
    app.config["KILN_RUNNER"].stop()


def test_index_and_static_files_are_served(client):
    c, _ = client
    assert b"Kiln process simulation" in c.get("/").data
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/style.css").status_code == 200
    assert c.get("/static/scene.js").status_code == 200
    page = c.get("/").data
    assert b'id="scene"' in page and b'id="strip"' in page and b'id="exaggerate"' in page
    assert c.get("/static/../server.py").status_code in (301, 308, 404)


def test_specs_describe_every_slider(client):
    c, _ = client
    data = c.get("/api/specs").get_json()
    assert len(data["specs"]) == len(data["defaults"]) > 40
    first = data["specs"][0]
    assert {"name", "group", "label", "unit", "default", "min", "max", "step", "help", "kind"} <= first.keys()
    assert data["channels"] == ["p1", "p2", "t"]


def test_state_returns_new_records_only(client):
    c, runner = client
    runner.advance(5)
    everything = c.get("/api/state").get_json()
    assert len(everything["records"]) == 5
    since = everything["records"][2]["time_s"]
    newer = c.get(f"/api/state?since={since}").get_json()
    assert [r["time_s"] for r in newer["records"]] == [r["time_s"] for r in everything["records"][3:]]


def test_slider_change_is_validated_and_applied(client):
    c, runner = client
    ok = c.post("/api/params", json={"chimney_height_m": 45})
    assert ok.status_code == 200 and runner.loop.p.chimney_height_m == 45
    bad = c.post("/api/params", json={"chimney_height_m": 9999})
    assert bad.status_code == 400 and "outside" in bad.get_json()["error"]
    assert runner.loop.p.chimney_height_m == 45                       # rejected change left no trace
    assert c.post("/api/params", json={"nope": 1}).status_code == 400


@pytest.mark.parametrize("removed", ["k_reuse", "reuse_extraction", "chimney_diameter_m", "k_upstream"])
def test_removed_parameters_are_rejected(client, removed):
    c, _ = client
    assert c.post("/api/params", json={removed: 1}).status_code == 400


def test_reset_to_defaults(client):
    c, runner = client
    c.post("/api/params", json={"kp": 4.0})
    c.post("/api/params", json={"reset": True})
    assert runner.loop.p.kp == pytest.approx(1.5)


def test_command_modes(client):
    c, runner = client
    c.post("/api/command", json={"text": "MAN 300"})
    runner.advance(2)
    assert c.get("/api/state").get_json()["records"][-1]["mode"] == "MAN"
    c.post("/api/command", json={"text": "garbage"})
    runner.advance(1)
    assert c.get("/api/state").get_json()["records"][-1]["mode"] == "OFF"


def test_faults_and_offsets(client):
    c, runner = client
    assert c.post("/api/fault", json={"channel": "p1", "fault": "open"}).status_code == 200
    runner.advance(2)
    last = c.get("/api/state").get_json()["records"][-1]
    assert last["status"] == "SENSOR_FAULT_SAFE_RPM" and last["counts_p1"] == 8000
    assert c.post("/api/fault", json={"channel": "p9", "fault": "open"}).status_code == 400
    assert c.post("/api/fault", json={"channel": "p1", "offset": 12}).get_json()["offsets"]["p1"] == 12


def test_pause_run_speed_and_reset(client):
    c, runner = client
    runner.advance(10)
    assert c.post("/api/control", json={"action": "pause", "speed": SPEEDS[-1]}).get_json() == {"running": False, "speed": SPEEDS[-1]}
    assert c.post("/api/control", json={"speed": 7}).status_code == 400
    assert c.post("/api/control", json={"action": "explode"}).status_code == 400
    c.post("/api/control", json={"action": "reset"})
    state = c.get("/api/state").get_json()
    assert state["records"] == [] and state["time_s"] == 0.0


def test_reset_keeps_slider_values_and_command(client):
    c, runner = client
    c.post("/api/params", json={"t_gas_c": 300})
    c.post("/api/command", json={"text": "PID 4.0"})
    c.post("/api/control", json={"action": "reset"})
    assert runner.loop.p.t_gas_c == 300
    runner.advance(1)
    assert runner.loop.command.value == 4.0


def test_background_thread_advances_the_simulation():
    import time
    app = create_app(autostart=True)
    runner = app.config["RUNNER"]
    try:
        deadline = time.time() + 3
        while time.time() < deadline and runner.loop.time_s < 3:
            time.sleep(0.05)
        assert runner.loop.time_s >= 3
    finally:
        runner.stop()
        app.config["KILN_RUNNER"].stop()


def test_state_carries_the_profile_of_the_latest_instant_only(client):
    c, runner = client
    runner.advance(5)
    state = c.get("/api/state").get_json()
    profile = state["profile"]
    assert {"stations", "chimney", "top", "ground", "geometry", "calcs", "pressure_exaggeration"} <= profile.keys()
    assert len(profile["chimney"]) == 20
    assert profile["geometry"]["height_m"] == pytest.approx(38.1)
    assert profile["calcs"]["q_plate_m3_s"] == pytest.approx(state["records"][-1]["flow_true_m3s"])
    assert all("profile" not in record for record in state["records"])     # history stays small


def test_profile_follows_a_slider_change(client):
    c, runner = client
    c.post("/api/params", json={"chimney_top_side_m": 0.5})
    runner.advance(1)
    assert c.get("/api/state").get_json()["profile"]["geometry"]["top_side_m"] == 0.5
