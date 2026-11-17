"""
Pins the PID / fan edge-case behaviour found by ``sim.pid_edge_cases`` (see project/pid-fan-report.md).

Several of these tests assert behaviour that is a BUG in fan-ctrl today (marked "today"). They document it so a fix
turns the test red on purpose; update the expectation in the same commit as the fix. None of them changes fan-ctrl.
"""
import math

import pytest

from sim import pid_edge_cases as pe
from sim.analysis import defaults

from command import Command
from fan_drive import FanDrive
from pid import PIDController
from utils import AttrDict

BASE = defaults()


# --------------------------------------------------------------------------- production PID, closed loop
def test_today_windup_without_anti_windup_takes_minutes_to_recover():
    prod = pe.unreachable_high(BASE, "prod")
    sim = pe.unreachable_high(BASE, "sim")
    assert prod["recover_s"] > 1000                 # about 29 min with the daemon's PID
    assert sim["recover_s"] < 60                    # the GUI's patched PID recovers in seconds


def test_prototype_pid_recovers_without_windup():
    assert pe.unreachable_high(BASE, "eng")["recover_s"] < 60
    assert pe.unreachable_low(BASE, "eng")["recover_s"] < 60


def test_today_manual_to_pid_kicks_the_fan():
    assert pe.manual_to_pid(BASE, "prod")["first_scan_jump_rpm"] > 30
    assert pe.manual_to_pid(BASE, "eng")["first_scan_jump_rpm"] == pytest.approx(0.0, abs=1.0)


def test_today_doubling_the_gains_jumps_the_fan_but_prototype_does_not():
    assert pe.gain_change(BASE, "prod")["rpm_jump"] > 50
    assert pe.gain_change(BASE, "eng")["rpm_jump"] < 1.0


def test_today_off_stops_the_fan_but_the_architecture_says_safe_speed():
    assert pe.pid_to_off(BASE, "prod")["rpm_after_off"] == 0
    assert pe.pid_to_off(BASE, "eng")["rpm_after_off"] == BASE["safe_rpm"]


def test_today_a_sensor_fault_gap_disturbs_the_flow_more_than_necessary():
    assert pe.fault_gap(BASE, "prod")["peak_dev_pct"] > 3 * pe.fault_gap(BASE, "eng")["peak_dev_pct"]


def test_prototype_matches_prod_tracking_on_a_plain_step():
    prod = pe.setpoint_step(BASE, "prod")["up"]
    eng = pe.setpoint_step(BASE, "eng")["up"]
    assert eng["settle_s"] == pytest.approx(prod["settle_s"], abs=10)
    assert eng["overshoot_pct"] < 1.0


def test_derivative_on_measurement_cuts_noise_jitter():
    assert pe.noise_jitter(BASE, "eng", 2.0)["rpm_std"] < 0.7 * pe.noise_jitter(BASE, "prod", 2.0)["rpm_std"]


# --------------------------------------------------------------------------- transmitter offsets (control law identical)
@pytest.mark.parametrize("channel,offset,sign", [("p1", 5, -1), ("p1", -5, 1), ("p2", 5, 1), ("p2", -5, -1)])
def test_a_5_pa_pressure_offset_moves_the_true_flow_by_about_8_percent(channel, offset, sign):
    error = pe.offset_effect(BASE, channel, offset)["error_pct"]
    assert math.copysign(1, error) == sign
    assert 6.0 < abs(error) < 10.0


# --------------------------------------------------------------------------- readability and the legacy value
def test_setpoint_below_the_readable_region_is_not_met():
    rows = {r["setpoint"]: r for r in pe.readability_scan(BASE)}
    assert rows[2.0]["true_end"] > 2.0 * 1.15       # controller thinks 2.0, plant delivers more than 2.5
    assert rows[3.0]["true_end"] == pytest.approx(3.0, rel=0.01)


def test_legacy_value_is_not_monotonic_in_fan_speed():
    values = [r["legacy"] for r in pe.legacy_curve(BASE) if r["legacy"] is not None]
    rises = [b > a for a, b in zip(values, values[1:])]
    assert any(rises) and not all(rises)            # rises then falls
    assert values[-1] < max(values) - 4


def test_today_pid_on_the_legacy_value_runs_away_in_the_upper_range():
    high = pe.legacy_pv_loop(BASE, 33.0)
    assert high["rpm_end"] == pytest.approx(450.0)          # setpoint above the value: fan pinned at maximum
    assert high["legacy_end"] < 33.0                         # and the value is still below the setpoint
    low = pe.legacy_pv_loop(BASE, 29.0)
    assert low["rpm_end"] == pytest.approx(220.0)


# --------------------------------------------------------------------------- unit-level edges (today)
def _pid(**kw):
    return PIDController(AttrDict({"kp": 1.5, "ki": 0.2, "kd": 1.0, "set_point": 0.45, **kw}))


def test_today_pid_nan_input_poisons_the_integral_permanently():
    c = _pid()
    c.compute(float("nan"), 0.0)
    assert math.isnan(c.compute(0.4, 1.0))                  # healthy input afterwards: still NaN
    c.reset()
    assert not math.isnan(c.compute(0.4, 0.0))              # only reset() recovers


def test_today_pid_none_input_raises():
    with pytest.raises(TypeError):
        _pid().compute(None, 1.0)


def test_today_backwards_clock_drains_the_integral():
    c = _pid()
    c.compute(0.4, 100.0)
    c.compute(0.4, 40.0)
    assert c._integral < 0


def test_today_tiny_time_step_makes_a_huge_derivative_spike():
    c = _pid()
    c.compute(0.4, 0.0)
    assert abs(c.compute(0.41, 1e-6)) > 1000


def test_today_integral_has_no_limit():
    c = _pid(kd=0.0)
    for t in range(600):
        c.compute(0.25, float(t))
    assert 0.2 * c._integral > 20                           # output about 24 against a 0..1 range


def test_today_setpoint_step_gives_a_derivative_kick():
    with_kick = _pid(); with_kick.compute(0.4, 0.0)
    with_kick.set_cfg(AttrDict({"kp": 1.5, "ki": 0.2, "kd": 1.0, "set_point": 0.60}))
    no_kd = _pid(kd=0.0); no_kd.compute(0.4, 0.0)
    no_kd.set_cfg(AttrDict({"kp": 1.5, "ki": 0.2, "kd": 0.0, "set_point": 0.60}))
    assert with_kick.compute(0.4, 1.0) - no_kd.compute(0.4, 1.0) == pytest.approx(0.15, abs=0.01)


def _drive(**kw):
    return FanDrive(AttrDict({"motor_min_rpm": 220, "motor_max_rpm": 450, "pid_min_rpm": 220, "pid_max_rpm": 450, **kw}))


def test_today_fan_drive_nan_commands_maximum_speed():
    d = _drive()
    d.set_rpm(float("nan"))
    assert d.commanded_rpm == 450
    d.set_output_percent(float("nan"))
    assert d.commanded_rpm == 450


def test_today_fan_drive_none_raises_and_percent_is_a_fraction():
    with pytest.raises(TypeError):
        _drive().set_rpm(None)
    d = _drive()
    d.set_output_percent(50)                                # a "percent" of 50 means 5000 %
    assert d.demanded_rpm > 10000 and d.commanded_rpm == 450


def test_today_fan_drive_off_commands_zero_and_ignores_resonance():
    d = _drive()
    d.set_rpm(300)
    d.off()
    assert d.commanded_rpm == 0
    d = _drive(motor_min_rpm=0)
    d.set_rpm(180)
    assert d.commanded_rpm == 180                           # inside 150..210; only the ACS560 critical-speed skip protects it


# --------------------------------------------------------------------------- Command parsing (today)
@pytest.mark.parametrize("text", ["", "   "])
def test_today_empty_command_raises_indexerror_not_valueerror(text):
    with pytest.raises(IndexError):                         # main.parse_cmd catches only ValueError
        Command(text)


def test_today_none_command_raises_attributeerror():
    with pytest.raises(AttributeError):
        Command(None)


@pytest.mark.parametrize("text", ["PID nan", "PID inf", "PID -5", "PID 3.6 junk", "MAN -50", "MAN 99999", "OFF now"])
def test_today_command_accepts_values_that_make_no_sense(text):
    Command(text)


def test_today_main_py_findings():
    f = pe.main_py_findings()
    assert f["source_reads_class_attribute_q_avg"] and f["that_expression_at_runtime"] == "raises AttributeError"
    assert f["passes_raw_pid_output_to_drive"] and f["off_means_zero_rpm"] and f["catches_only_valueerror"]
    assert not f["resets_pid_on_mode_change"]
    assert f["cmd_value_uses_in_file"] == 1                 # the PID setpoint is never taken from "PID <sv>"


# --------------------------------------------------------------------------- the prototype itself
def test_eng_pid_limits_output_and_unwinds():
    c = pe.EngPID(kp=40, ti=8, td=0, rpm_min=220, rpm_max=450)
    for t in range(300):
        out = c.compute(6.0, 4.0, float(t))
    assert out == 450
    assert abs(c._i) < 2000                                  # bounded: back-calculation holds it near the limit


def test_eng_pid_ignores_bad_input_and_time_gaps():
    c = pe.EngPID(kp=40, ti=8, td=0, rpm_min=220, rpm_max=450)
    c.track(300, 3.6, 3.6)
    assert c.compute(3.6, float("nan"), 1.0) == 300         # holds
    assert c.compute(3.6, 3.6, 2.0) == pytest.approx(300)
    i_before = c._i
    c.compute(3.0, 3.6, 3600.0)                              # an hour-long gap must not integrate
    assert c._i == pytest.approx(i_before)
