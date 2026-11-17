import pytest

from sim import analysis as an


@pytest.fixture(scope="module")
def base():
    return an.defaults()


def test_rpm_for_flow_hits_the_target(base):
    p = an.build(base)
    rpm = an.rpm_for_flow(p, 3.6)
    assert an.flow_at(p, rpm) == pytest.approx(3.6, abs=1e-6)


def test_rpm_for_flow_is_zero_when_draft_alone_is_enough_and_none_when_unreachable(base):
    p = an.build(base)
    assert an.rpm_for_flow(p, 1.0) == 0.0
    assert an.rpm_for_flow(p, 50.0) is None


def test_tornado_is_sorted_by_effect_and_has_the_expected_leaders(base):
    rows = an.tornado(base, relative=0.10)
    swings = [abs(r["hi"]["rpm_needed"] - r["lo"]["rpm_needed"]) for r in rows]
    assert swings == sorted(swings, reverse=True)
    assert rows[0]["name"] == "fan_rated_rpm"
    assert {"restriction_free_area_m2", "kiln_free_area_m2"} <= {r["name"] for r in rows[:5]}


def test_relative_tornado_skips_zero_valued_parameters(base):
    names = {r["name"] for r in an.tornado(base, relative=0.10)}
    assert "kiln_gauge_pa" not in names                    # default 0 has no relative change
    assert "kiln_gauge_pa" in {r["name"] for r in an.tornado(base)}


def test_directions_of_the_main_effects(base):
    rows = {r["name"]: r for r in an.tornado(base, relative=0.10)}
    assert rows["kiln_free_area_m2"]["hi"]["rpm_needed"] < rows["kiln_free_area_m2"]["lo"]["rpm_needed"]   # more open kiln, less fan
    assert rows["gas_molar_mass_g_mol"]["hi"]["rpm_needed"] > rows["gas_molar_mass_g_mol"]["lo"]["rpm_needed"]
    assert rows["chimney_height_m"]["hi"]["q_natural"] > rows["chimney_height_m"]["lo"]["q_natural"]


def test_fan_adds_less_flow_when_the_draft_is_stronger(base):
    rows = an.fan_effect_vs_draft(base)
    weakest = min(rows, key=lambda r: r["draft"])
    strongest = max(rows, key=lambda r: r["draft"])
    assert weakest["fan_adds"] > strongest["fan_adds"]


def test_envelope_floor_rises_in_cold_weather(base):
    rows = an.envelope_vs_ambient(base, (5, 40))
    assert rows[0]["q_min"] > rows[1]["q_min"]
    assert all(r["q_max"] > r["q_min"] for r in rows)


def test_correct_assumptions_give_the_setpoint_as_the_true_flow(base):
    assert an.true_flow_when_controller_holds_setpoint(base) == pytest.approx(3.6, rel=1e-6)


def test_wrong_cd_assumption_scales_the_true_flow(base):
    assert an.true_flow_when_controller_holds_setpoint(base, est_cd_error_pct=5) == pytest.approx(3.6 / 1.05, rel=1e-4)


def test_p1_and_p2_drift_push_the_true_flow_in_opposite_directions(base):
    p1 = an.true_flow_when_controller_holds_setpoint(base, p1_offset=5)
    p2 = an.true_flow_when_controller_holds_setpoint(base, p2_offset=5)
    assert p1 < 3.6 < p2
    assert an.true_flow_when_controller_holds_setpoint(base, p1_offset=5, p2_offset=5) == pytest.approx(3.6, rel=1e-3)


def test_plate_beta_trades_signal_against_fan_work(base):
    rows = an.plate_beta_study(base, betas=(0.5, 0.7))
    assert rows[0]["plate_dp"] > rows[1]["plate_dp"]
    assert rows[0]["rpm_needed"] > rows[1]["rpm_needed"]
    assert rows[0]["pct_per_count"] < rows[1]["pct_per_count"]


def test_resolution_is_coarser_at_low_flow(base):
    rows = an.flow_resolution_vs_flow(base, flows=(2.5, 4.0))
    assert rows[0]["pct_per_count"] > rows[1]["pct_per_count"]


def test_step_metrics_report_overshoot_and_settling(base):
    records = an.step_records(base, kp=0.5, ki=0.5)
    metrics = an.step_metrics(records, 300.0, 3.2, 3.8)
    assert metrics["overshoot_pct"] > 1.0 and metrics["settle_s"] < 60


def test_cold_front_is_rejected_quickly(base):
    result = an.disturbance_response(base)
    assert result["peak_deviation"] < 0.3 and result["recovery_s"] < 60


def test_narrow_chimney_top_costs_exit_loss_and_fan_speed(base):
    rows = an.chimney_taper_study(base, top_sides=(0.5, 1.524))
    assert rows[0]["loss_exit"] > rows[1]["loss_exit"]
    assert rows[0]["rpm_needed"] > rows[1]["rpm_needed"]
    assert rows[0]["q_fixed_rpm"] < rows[1]["q_fixed_rpm"]
