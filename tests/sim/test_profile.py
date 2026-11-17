import json
import math

import pytest

from sim.gas import air_viscosity, barometric_pressure
from sim.loop import ClosedLoop
from sim.params import make_params
from sim.plant import solve_steady
from sim.profile import build_profile, PRESSURE_EXAGGERATION, MIN_DRAWN_DENSITY

AMB = 30.0
GAS = 130.0
RPM = 380.0


@pytest.fixture(scope="module")
def case():
    p = make_params()
    op = solve_steady(p, RPM, GAS, AMB)
    return p, op, build_profile(p, op, AMB)


def test_profile_is_plain_json_data(case):
    _, _, profile = case
    assert json.loads(json.dumps(profile)) == profile


def test_stations_follow_the_gas_path(case):
    _, op, profile = case
    assert [s["key"] for s in profile["stations"]] == ["kiln", "fan_in", "fan_out", "p1", "p2", "chimney_base"]
    by_key = {s["key"]: s for s in profile["stations"]}
    assert by_key["p1"]["p_gauge_pa"] == pytest.approx(op.p1_pa)
    assert by_key["p2"]["p_gauge_pa"] == pytest.approx(op.p2_pa)
    assert by_key["fan_in"]["p_gauge_pa"] < 0 < by_key["fan_out"]["p_gauge_pa"]
    assert by_key["p1"]["p_abs_pa"] == pytest.approx(101325 + op.p1_pa)


def test_mass_is_conserved_along_the_whole_path(case):
    p, op, profile = case
    duct_area = math.pi / 4 * p.duct_diameter_m ** 2
    for s in profile["stations"][1:]:
        assert s["rho"] * s["v_m_s"] * duct_area == pytest.approx(op.mass_flow_kg_s)
    for s in profile["chimney"]:
        assert s["rho"] * s["v_m_s"] * s["side_m"] ** 2 == pytest.approx(op.mass_flow_kg_s)
    top = profile["top"]
    assert top["rho"] * top["v_m_s"] * top["side_m"] ** 2 == pytest.approx(op.mass_flow_kg_s)


def test_gas_speeds_up_and_cools_as_the_chimney_narrows(case):
    _, _, profile = case
    speeds = [s["v_m_s"] for s in profile["chimney"]]
    temps = [s["t_c"] for s in profile["chimney"]]
    assert speeds == sorted(speeds) and speeds[-1] > 2 * speeds[0]
    assert temps == sorted(temps, reverse=True)
    assert profile["top"]["v_m_s"] > speeds[-1]


def test_chimney_pressure_recovers_to_the_exit_loss_at_the_top(case):
    """Relative to the outside air at each height: suction at the base, rising to the exit loss at the top."""
    _, op, profile = case
    gauges = [s["p_gauge_local_pa"] for s in profile["chimney"]]
    assert gauges[0] < 0 and gauges == sorted(gauges)
    assert profile["top"]["p_gauge_local_pa"] == pytest.approx(op.loss_exit_pa, abs=1e-6)


def test_outside_air_matches_the_barometric_formula(case):
    p, _, profile = case
    top = profile["top"]["outside"]
    assert top["p_abs_pa"] == pytest.approx(barometric_pressure(p.p_atm_pa, p.chimney_height_m, AMB))
    assert profile["ground"]["p_abs_pa"] - top["p_abs_pa"] == pytest.approx(434, abs=4)   # 1.165 * 9.807 * 38.1
    assert top["rho"] < profile["ground"]["rho"]


# --------------------------------------------------------------------------- particle densities
def test_true_particle_density_is_pressure_over_temperature(case):
    _, _, profile = case
    hot = profile["stations"][3]
    expected = (hot["p_abs_pa"] / 101325) * (AMB + 273.15) / (GAS + 273.15)
    assert hot["density_true"] == pytest.approx(expected)
    assert hot["density_true"] == pytest.approx(0.75, abs=0.01)          # hot gas is a quarter thinner
    assert profile["ground"]["density_true"] == 1.0


def test_true_scale_hides_pressure_and_the_exaggerated_scale_shows_it(case):
    _, _, profile = case
    by_key = {s["key"]: s for s in profile["stations"]}
    true_spread = by_key["fan_out"]["density_true"] - by_key["fan_in"]["density_true"]
    drawn_spread = by_key["fan_out"]["density_exaggerated"] - by_key["fan_in"]["density_exaggerated"]
    assert true_spread < 0.005                       # under half a percent: invisible
    assert drawn_spread > 0.15                       # clearly visible
    assert drawn_spread == pytest.approx(true_spread * PRESSURE_EXAGGERATION, rel=0.01)
    sky_top = profile["top"]["outside"]
    assert sky_top["density_true"] == pytest.approx(0.9957, abs=0.0005)
    assert sky_top["density_exaggerated"] == pytest.approx(0.57, abs=0.01)


def test_drawn_density_never_goes_to_zero():
    p = make_params({"chimney_height_m": 60, "t_gas_c": 500})
    profile = build_profile(p, solve_steady(p, 450, 500, AMB), AMB)
    assert all(s["density_exaggerated"] >= MIN_DRAWN_DENSITY for s in profile["chimney"])


# --------------------------------------------------------------------------- calculations (hand checks)
def test_velocities_are_flow_over_area(case):
    p, op, profile = case
    v = profile["calcs"]["velocity"]
    assert v["duct_m_s"] == pytest.approx(op.q_m3_s / (math.pi / 4 * 1.25 ** 2))
    assert v["plate_bore_m_s"] == pytest.approx(v["duct_m_s"] / p.plate_beta ** 2)
    assert v["chimney_exit_m_s"] == pytest.approx(profile["top"]["v_m_s"])
    assert v["chimney_exit_m_s"] > v["chimney_base_m_s"]


def test_reynolds_number_matches_a_hand_calculation(case):
    p, op, profile = case
    v = profile["calcs"]["velocity"]["duct_m_s"]
    expected = op.rho_plate * v * p.duct_diameter_m / air_viscosity(GAS)
    assert profile["calcs"]["reynolds"]["duct"] == pytest.approx(expected)
    assert profile["calcs"]["reynolds"]["duct"] > 4000              # turbulent, as the loss model assumes


def test_pressure_budget_closes_at_steady_state(case):
    _, op, profile = case
    budget = profile["calcs"]["budget"]
    assert sum(budget["sources"].values()) == pytest.approx(sum(budget["losses"].values()), abs=1e-6)
    assert budget["imbalance_pa"] == pytest.approx(0.0, abs=1e-6)
    assert budget["sources"]["draft_pa"] == pytest.approx(op.draft_pa)
    assert budget["losses"]["restriction_pa"] == pytest.approx(op.loss_restriction_pa)


def test_fan_power_matches_a_hand_calculation(case):
    p, op, profile = case
    calcs = profile["calcs"]
    assert calcs["fan_air_power_w"] == pytest.approx(op.q_m3_s * op.fan_dp_pa)
    assert calcs["fan_shaft_power_w"] == pytest.approx(op.q_m3_s * op.fan_dp_pa / p.fan_efficiency)
    assert 500 < calcs["fan_air_power_w"] < 3000                    # about 1 kW of air power


def test_heat_figures_match_hand_calculations(case):
    p, op, profile = case
    calcs = profile["calcs"]
    assert calcs["heat_carried_w"] == pytest.approx(op.mass_flow_kg_s * p.gas_cp_j_kg_k * (GAS - AMB))
    assert calcs["heat_lost_chimney_w"] == pytest.approx(
        op.mass_flow_kg_s * p.gas_cp_j_kg_k * (GAS - op.t_chimney_top_c))
    assert 0 < calcs["heat_lost_chimney_w"] < calcs["heat_carried_w"]


def test_draft_share_is_its_part_of_the_driving_pressure(case):
    _, op, profile = case
    assert profile["calcs"]["draft_share"] == pytest.approx(op.draft_pa / (op.draft_pa + op.fan_dp_pa))


def test_stopped_fan_means_all_the_push_is_draft():
    p = make_params()
    profile = build_profile(p, solve_steady(p, 0, GAS, AMB), AMB)
    assert profile["calcs"]["draft_share"] == pytest.approx(1.0)
    assert profile["calcs"]["fan_shaft_power_w"] == 0.0


def test_profile_at_zero_flow_has_no_velocity_and_does_not_fail():
    p = make_params({"t_gas_c": AMB, "gas_molar_mass_g_mol": 28.96})
    profile = build_profile(p, solve_steady(p, 0, AMB, AMB), AMB)
    assert profile["calcs"]["mass_flow_kg_s"] == 0.0
    assert profile["calcs"]["residence_time_chimney_s"] is None
    assert all(s["v_m_s"] == 0.0 for s in profile["chimney"])


# --------------------------------------------------------------------------- loop
def test_loop_gives_a_profile_before_and_after_stepping():
    loop = ClosedLoop(make_params({"p_noise_pa": 0, "t_noise_c": 0}))
    before = loop.profile()
    assert before["calcs"]["q_plate_m3_s"] > 0
    for _ in range(300):
        record = loop.step()
    after = loop.profile()
    assert after["calcs"]["q_plate_m3_s"] == pytest.approx(record["flow_true_m3s"])
    assert {s["key"]: s for s in after["stations"]}["p1"]["p_gauge_pa"] == pytest.approx(record["p1_pa"])
    assert abs(after["calcs"]["budget"]["imbalance_pa"]) < 1.0       # settled
