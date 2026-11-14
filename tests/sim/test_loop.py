import pytest

from sim.instruments import FAULT_OPEN, FAULT_NONE
from sim.loop import ClosedLoop
from sim.params import make_params
from sim.plant import solve_steady


def run(loop: ClosedLoop, seconds: float) -> list[dict]:
    return [loop.step() for _ in range(round(seconds / loop.p.scan_interval_s))]


def quiet(**overrides):
    """No sensor noise, so assertions about settling can be tight."""
    return make_params({"p_noise_pa": 0, "t_noise_c": 0, **overrides})


# --------------------------------------------------------------------------- PID tracking
def test_pid_settles_on_the_setpoint():
    loop = ClosedLoop(quiet(), "PID 4.5")
    last = run(loop, 400)[-1]
    assert last["status"] == "PID"
    assert last["flow_true_m3s"] == pytest.approx(4.5, rel=0.02)
    assert last["flow_estimate_m3s"] == pytest.approx(4.5, rel=0.02)


def test_pid_follows_a_setpoint_step_without_large_overshoot():
    loop = ClosedLoop(quiet(), "PID 4.5")
    run(loop, 300)
    loop.set_command("PID 5.5")
    records = run(loop, 300)
    assert max(r["flow_true_m3s"] for r in records) < 5.5 * 1.10
    assert records[-1]["flow_true_m3s"] == pytest.approx(5.5, rel=0.02)


def test_pid_rejects_a_weather_disturbance():
    loop = ClosedLoop(quiet(), "PID 4.5")
    run(loop, 300)
    colder = loop.p.__class__(**{**loop.p.__dict__, "t_amb_c": 0.0})    # cold front: more draft
    loop.set_params(colder)
    records = run(loop, 400)
    assert records[-1]["flow_true_m3s"] == pytest.approx(4.5, rel=0.02)


def test_noise_does_not_stop_it_regulating():
    loop = ClosedLoop(make_params(), "PID 4.5", seed=3)
    records = run(loop, 400)[-100:]
    mean = sum(r["flow_true_m3s"] for r in records) / len(records)
    assert mean == pytest.approx(4.5, rel=0.03)


def test_same_seed_gives_identical_runs():
    a = run(ClosedLoop(make_params(), "PID 4.5", seed=5), 60)
    b = run(ClosedLoop(make_params(), "PID 4.5", seed=5), 60)
    assert a == b


# --------------------------------------------------------------------------- limits
def test_setpoint_below_natural_flow_pins_the_fan_at_minimum():
    p = quiet()
    natural = solve_steady(p, 0, p.t_gas_c, p.t_amb_c).q_m3_s
    loop = ClosedLoop(p, f"PID {natural - 1.0:.2f}")
    last = run(loop, 300)[-1]
    assert last["rpm_commanded"] == pytest.approx(p.motor_min_rpm)
    assert last["flow_true_m3s"] > natural - 1.0          # cannot reach it: draft alone is too strong


def test_setpoint_above_fan_capability_pins_the_fan_at_maximum():
    p = quiet()
    loop = ClosedLoop(p, "PID 20")
    last = run(loop, 300)[-1]
    assert last["rpm_commanded"] == pytest.approx(p.motor_max_rpm)


def recovery_time(anti_windup: float) -> float:
    """Seconds to get within 5 % of the new setpoint after a long spell pinned at minimum speed."""
    loop = ClosedLoop(quiet(anti_windup=anti_windup), "PID 1.0")        # unreachable: below natural flow
    run(loop, 600)
    loop.set_command("PID 4.5")
    for i, r in enumerate(run(loop, 600), start=1):
        if abs(r["flow_true_m3s"] - 4.5) < 0.05 * 4.5:
            return i * loop.p.scan_interval_s
    return float("inf")


def test_anti_windup_makes_recovery_from_saturation_faster():
    with_aw = recovery_time(1.0)
    without_aw = recovery_time(0.0)
    assert with_aw < 100
    assert with_aw < without_aw


def test_minimum_speed_of_zero_lets_the_fan_stop():
    p = quiet(motor_min_rpm=0, pid_min_rpm=0)
    natural = solve_steady(p, 0, p.t_gas_c, p.t_amb_c).q_m3_s
    last = run(ClosedLoop(p, f"PID {natural - 1.0:.2f}"), 300)[-1]
    assert last["rpm_commanded"] == 0.0


# --------------------------------------------------------------------------- modes
def test_manual_mode_holds_the_requested_speed():
    loop = ClosedLoop(quiet(), "MAN 900")
    last = run(loop, 120)[-1]
    assert last["status"] == "MANUAL" and last["pid_output"] is None
    assert last["rpm_actual"] == pytest.approx(900, abs=1)
    assert last["flow_true_m3s"] == pytest.approx(solve_steady(loop.p, 900, 250, 25).q_m3_s, rel=0.01)


def test_manual_speed_is_clamped_to_the_motor_range():
    loop = ClosedLoop(quiet(), "MAN 99999")
    assert run(loop, 5)[-1]["rpm_commanded"] == pytest.approx(loop.p.motor_max_rpm)


def test_off_means_safe_speed_not_stopped():
    loop = ClosedLoop(quiet(safe_rpm=600), "OFF")
    last = run(loop, 120)[-1]
    assert last["status"] == "OFF_SAFE_RPM"
    assert last["rpm_actual"] == pytest.approx(600, abs=1)


@pytest.mark.parametrize("bad", ["", "FAST 3", "PID", "PID abc", "MAN"])
def test_invalid_command_fails_closed_to_off(bad):
    loop = ClosedLoop(quiet(), "PID 4.5")
    loop.set_command(bad)
    assert run(loop, 1)[-1]["mode"] == "OFF"


# --------------------------------------------------------------------------- faults
@pytest.mark.parametrize("channel", ["p1", "p2", "t"])
def test_open_circuit_on_any_sensor_drops_to_safe_speed(channel):
    loop = ClosedLoop(quiet(safe_rpm=600), "PID 5.5")
    run(loop, 200)
    loop.set_fault(channel, FAULT_OPEN)
    last = run(loop, 120)[-1]
    assert last["status"] == "SENSOR_FAULT_SAFE_RPM"
    assert last["flow_estimate_m3s"] is None and last["pid_output"] is None
    assert last["rpm_actual"] == pytest.approx(600, abs=1)
    assert last["counts_" + channel] == 8000


def test_loop_resumes_control_after_the_sensor_is_repaired():
    loop = ClosedLoop(quiet(), "PID 4.5")
    run(loop, 100)
    loop.set_fault("p2", FAULT_OPEN)
    run(loop, 30)
    loop.set_fault("p2", FAULT_NONE)
    last = run(loop, 400)[-1]
    assert last["status"] == "PID"
    assert last["flow_true_m3s"] == pytest.approx(4.5, rel=0.02)


def test_unknown_fault_or_channel_is_rejected():
    loop = ClosedLoop(quiet())
    with pytest.raises(ValueError):
        loop.set_fault("p3", FAULT_OPEN)
    with pytest.raises(ValueError):
        loop.set_fault("p1", "melted")
    with pytest.raises(ValueError):
        loop.set_offset("x", 1.0)


def test_transmitter_drift_biases_the_true_flow():
    loop = ClosedLoop(quiet(), "PID 4.5")
    loop.set_offset("p2", 30.0)            # P2 reads 30 Pa high -> dP looks smaller -> controller under-reads
    last = run(loop, 500)[-1]
    assert last["flow_estimate_m3s"] == pytest.approx(4.5, rel=0.02)
    assert last["flow_true_m3s"] > 4.6      # the plant is running more flow than the controller believes


# --------------------------------------------------------------------------- estimate error and live params
def test_wrong_plate_cd_assumption_shows_up_as_flow_error():
    loop = ClosedLoop(quiet(est_cd_error_pct=10), "PID 4.5")
    last = run(loop, 400)[-1]
    assert last["flow_estimate_m3s"] == pytest.approx(4.5, rel=0.02)
    assert last["flow_true_m3s"] == pytest.approx(4.5 / 1.10, rel=0.02)


def test_slider_change_takes_effect_on_the_next_scan_and_state_is_kept():
    loop = ClosedLoop(quiet(), "MAN 600")
    before = run(loop, 100)[-1]
    taller = loop.p.__class__(**{**loop.p.__dict__, "chimney_height_m": 50.0})
    loop.set_params(taller)
    first_after = loop.step()
    later = run(loop, 100)[-1]
    total_change = later["flow_true_m3s"] - before["flow_true_m3s"]
    assert total_change > 0.3                                                      # it does respond
    assert first_after["flow_true_m3s"] - before["flow_true_m3s"] < 0.5 * total_change   # but not as a jump
    assert later["draft_pa"] > before["draft_pa"]


def test_record_reports_natural_only_flow_for_the_gui():
    loop = ClosedLoop(quiet(), "PID 4.5")
    rec = run(loop, 5)[-1]
    expected = solve_steady(loop.p, 0, loop.plant.t_gas_c, 25).q_m3_s
    assert rec["flow_natural_only_m3s"] == pytest.approx(expected)
    assert {"time_s", "rpm_actual", "p1_pa", "p2_pa", "draft_pa", "fan_dp_pa", "counts_p1"} <= rec.keys()


def test_firing_cycle_swing_is_visible_in_gas_temperature_and_rejected_by_pid():
    loop = ClosedLoop(quiet(t_gas_swing_k=60, t_gas_period_s=600), "PID 4.5")
    records = run(loop, 1200)
    gas = [r["t_gas_c"] for r in records]
    assert max(gas) - min(gas) > 40
    late = records[600:]
    assert max(abs(r["flow_true_m3s"] - 4.5) for r in late) < 0.3
