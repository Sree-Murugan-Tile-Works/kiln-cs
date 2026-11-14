import math

import pytest

from sim.gas import density, AIR_MOLAR_MASS_G_MOL
from sim.instruments import estimate_flow
from sim.params import make_params
from sim.plant import (Plant, solve_steady, operating_point, environment, plate_temperature,
                       _loss_coefficients, PERMANENT_LOSS_EXPONENT)

AMB = 25.0


def no_draft_params(**overrides):
    """Gas as warm and as heavy as the outside air: no buoyancy, so only the fan drives flow."""
    return make_params({"t_gas_c": AMB, "t_amb_c": AMB, "gas_molar_mass_g_mol": AIR_MOLAR_MASS_G_MOL,
                        **overrides})


# --------------------------------------------------------------------------- gas
def test_density_ideal_gas_air_at_20c():
    assert density(101325, 20, 28.96) == pytest.approx(1.204, abs=0.002)


def test_hotter_gas_is_lighter():
    assert density(101325, 300, 28.5) < density(101325, 100, 28.5)


# --------------------------------------------------------------------------- natural draft
def test_no_draft_and_no_flow_without_fan_when_gas_matches_ambient():
    op = solve_steady(no_draft_params(), rpm=0, t_gas_c=AMB, t_amb_c=AMB)
    assert op.draft_pa == pytest.approx(0.0, abs=1e-9)
    assert op.q_m3_s == 0.0 and op.stalled


def test_hot_gas_flows_by_natural_draft_alone():
    op = solve_steady(make_params(), rpm=0, t_gas_c=250, t_amb_c=AMB)
    assert op.draft_pa > 50
    assert op.q_m3_s > 1.0 and not op.stalled


def test_draft_grows_with_chimney_height():
    low = solve_steady(make_params({"chimney_height_m": 20}), 0, 250, AMB)
    high = solve_steady(make_params({"chimney_height_m": 40}), 0, 250, AMB)
    assert high.draft_pa > low.draft_pa
    assert high.q_m3_s > low.q_m3_s


def test_draft_grows_with_gas_temperature():
    cool = solve_steady(make_params(), 0, 120, AMB)
    hot = solve_steady(make_params(), 0, 350, AMB)
    assert hot.draft_pa > cool.draft_pa and hot.q_m3_s > cool.q_m3_s


def test_cold_weather_increases_draft():
    warm = solve_steady(make_params(), 0, 250, 35)
    cold = solve_steady(make_params(), 0, 250, -5)
    assert cold.draft_pa > warm.draft_pa


def test_chimney_wall_losses_reduce_draft():
    insulated = solve_steady(make_params({"chimney_u_w_m2k": 0}), 0, 250, AMB)
    leaky = solve_steady(make_params({"chimney_u_w_m2k": 15}), 0, 250, AMB)
    assert leaky.t_chimney_mean_c < insulated.t_chimney_mean_c
    assert leaky.draft_pa < insulated.draft_pa


def test_gas_cools_less_at_higher_flow():
    p = make_params()
    slow = solve_steady(p, 0, 250, AMB)
    fast = solve_steady(p, 1500, 250, AMB)
    assert fast.t_chimney_mean_c > slow.t_chimney_mean_c
    assert fast.t_chimney_top_c > slow.t_chimney_top_c


def reversed_draft_params():
    """Gas clearly colder than the air outside (and equally heavy per mole): the stack pushes backwards."""
    return make_params({"t_amb_c": 45, "t_gas_c": 25, "gas_molar_mass_g_mol": AIR_MOLAR_MASS_G_MOL})


def test_draft_can_reverse_and_flow_stalls_without_fan():
    op = solve_steady(reversed_draft_params(), 0, 25, 45)
    assert op.draft_pa < 0
    assert op.stalled and op.q_m3_s == 0.0


def test_fan_overcomes_reversed_draft():
    assert solve_steady(reversed_draft_params(), 1500, 25, 45).q_m3_s > 0.5


# --------------------------------------------------------------------------- fan
def test_flow_rises_monotonically_with_fan_speed():
    p = make_params()
    flows = [solve_steady(p, rpm, 250, AMB).q_m3_s for rpm in (0, 300, 600, 900, 1200, 1500)]
    assert flows == sorted(flows) and flows[-1] > flows[0]


def test_flow_proportional_to_speed_when_there_is_no_draft():
    p = no_draft_params()
    q500 = solve_steady(p, 500, AMB, AMB).q_m3_s
    q1000 = solve_steady(p, 1000, AMB, AMB).q_m3_s
    assert q1000 / q500 == pytest.approx(2.0, rel=1e-6)   # affinity law Q ~ N


def test_fan_adds_less_flow_when_natural_draft_is_strong():
    """The core property of this system: the fan's effect depends on the draft already present."""
    cold_kiln = make_params()
    gain_no_draft = (solve_steady(no_draft_params(), 1000, AMB, AMB).q_m3_s
                     - solve_steady(no_draft_params(), 0, AMB, AMB).q_m3_s)
    gain_with_draft = (solve_steady(cold_kiln, 1000, 250, AMB).q_m3_s
                       - solve_steady(cold_kiln, 0, 250, AMB).q_m3_s)
    assert gain_with_draft < gain_no_draft


def test_stopped_fan_is_a_small_restriction_not_a_blockage():
    p = make_params()
    op = solve_steady(p, 0, 250, AMB)
    assert op.fan_dp_pa < 0                      # drag, no pressure added
    assert op.q_m3_s > 3.0                       # but flow still passes


# --------------------------------------------------------------------------- balance and plate
@pytest.mark.parametrize("rpm", [0, 400, 1000, 1500])
def test_pressure_balance_closes_at_steady_state(rpm):
    p = make_params()
    op = solve_steady(p, rpm, 250, AMB)
    k = _loss_coefficients(p)
    m = op.mass_flow_kg_s
    rho_amb = density(p.p_atm_pa, AMB, AIR_MOLAR_MASS_G_MOL)
    rho_plate = op.rho_plate
    rho_reuse = density(p.p_atm_pa, (op.t_kiln_c + op.t_plate_c) / 2, p.gas_molar_mass_g_mol)
    rho_chim = density(p.p_atm_pa, op.t_chimney_mean_c, p.gas_molar_mass_g_mol)
    losses = ((k.k_upstream + k.k_plate_loop) / rho_plate + k.k_reuse / rho_reuse + k.k_chimney / rho_chim) * m ** 2
    assert op.draft_pa == pytest.approx(9.80665 * p.chimney_height_m * (rho_amb - rho_chim))
    assert op.draft_pa + op.fan_dp_pa - losses == pytest.approx(0.0, abs=1e-6)


def test_gauge_pressures_go_negative_under_suction():
    op = solve_steady(make_params(), 800, 250, AMB)
    assert op.p1_pa < 0 and op.p2_pa < op.p1_pa
    assert op.p1_pa - op.p2_pa == pytest.approx(op.plate_dp_pa)


def test_kiln_gauge_pressure_shifts_p1_and_p2_but_not_flow_or_plate_dp():
    base = solve_steady(make_params(), 800, 250, AMB)
    shifted = solve_steady(make_params({"kiln_gauge_pa": 20}), 800, 250, AMB)
    assert shifted.p1_pa == pytest.approx(base.p1_pa + 20)
    assert shifted.plate_dp_pa == pytest.approx(base.plate_dp_pa)


def test_plate_dp_scales_with_flow_squared():
    p = make_params()
    ratios = []
    for rpm in (0, 600, 1500):
        op = solve_steady(p, rpm, 250, AMB)
        ratios.append(op.plate_dp_pa / op.q_m3_s ** 2)
    assert ratios == pytest.approx([ratios[0]] * 3, rel=1e-9)


def test_smaller_plate_bore_gives_bigger_dp_and_less_flow():
    open_plate = solve_steady(make_params({"plate_beta": 0.7}), 800, 250, AMB)
    tight_plate = solve_steady(make_params({"plate_beta": 0.4}), 800, 250, AMB)
    assert tight_plate.plate_dp_pa > open_plate.plate_dp_pa
    assert tight_plate.q_m3_s < open_plate.q_m3_s


def test_permanent_loss_exponent_is_the_documented_one():
    assert PERMANENT_LOSS_EXPONENT == 1.9
    k = _loss_coefficients(make_params())
    assert k.k_plate_loop == pytest.approx(k.k_plate_full * (1 - 0.6 ** 1.9))


# --------------------------------------------------------------------------- flow estimate
def test_estimator_recovers_true_flow_when_assumptions_are_right():
    p = make_params()
    op = solve_steady(p, 900, 250, AMB)
    assert estimate_flow(p, op.p1_pa, op.p2_pa, op.t_plate_c) == pytest.approx(op.q_m3_s, rel=1e-9)


def test_estimator_cd_error_scales_the_estimate():
    base = make_params()
    wrong = make_params({"est_cd_error_pct": 5})
    op = solve_steady(base, 900, 250, AMB)
    ratio = (estimate_flow(wrong, op.p1_pa, op.p2_pa, 250) / estimate_flow(base, op.p1_pa, op.p2_pa, 250))
    assert ratio == pytest.approx(1.05)


def test_estimator_heavier_assumed_gas_reads_low():
    base = make_params()
    heavy = make_params({"est_molar_mass_g_mol": 31})
    op = solve_steady(base, 900, 250, AMB)
    assert estimate_flow(heavy, op.p1_pa, op.p2_pa, 250) < estimate_flow(base, op.p1_pa, op.p2_pa, 250)


def test_estimator_returns_zero_for_no_or_negative_dp():
    p = make_params()
    assert estimate_flow(p, -10, -10, 250) == 0.0
    assert estimate_flow(p, -20, -10, 250) == 0.0


# --------------------------------------------------------------------------- dynamics
def test_plant_starts_at_steady_state():
    p = make_params()
    plant = Plant(p, 800, 250, AMB)
    op = plant.step(0.1, 800, 250, AMB)
    assert op.q_m3_s == pytest.approx(solve_steady(p, 800, 250, AMB).q_m3_s, rel=1e-3)


def test_step_response_rises_smoothly_to_the_new_steady_state():
    p = make_params()
    plant = Plant(p, 200, 250, AMB)
    flows = [plant.step(0.5, 1500, 250, AMB).q_m3_s for _ in range(240)]   # 120 s
    assert all(b >= a - 1e-12 for a, b in zip(flows, flows[1:]))           # no overshoot or wobble
    assert flows[-1] == pytest.approx(solve_steady(p, 1500, 250, AMB).q_m3_s, rel=0.01)


def test_drive_ramp_limits_how_fast_speed_can_change():
    p = make_params({"drive_ramp_rpm_s": 100, "motor_tau_s": 0.1})
    plant = Plant(p, 200, 250, AMB)
    for _ in range(10):
        plant.step(0.1, 1500, 250, AMB)       # 1 s of simulated time
    assert plant.rpm <= 200 + 100 * 1.0 + 1e-6


def test_gas_temperature_lags_the_kiln():
    p = make_params({"gas_temp_tau_s": 60})
    plant = Plant(p, 800, 200, AMB)
    for _ in range(60):
        plant.step(1.0, 800, 300, AMB)         # 60 s = one time constant
    assert plant.t_gas_c == pytest.approx(200 + 100 * (1 - math.exp(-1)), abs=0.5)


def test_environment_swings_around_the_base_values():
    p = make_params({"t_amb_swing_k": 10, "t_amb_period_s": 400, "t_gas_swing_k": 40, "t_gas_period_s": 800})
    amb0, gas0 = environment(p, 0)
    amb_q, gas_q = environment(p, 100)         # quarter of the ambient period / eighth of the gas period
    assert amb0 == pytest.approx(25.0) and gas0 == pytest.approx(250.0)
    assert amb_q == pytest.approx(35.0)
    assert gas_q == pytest.approx(250 + 40 * math.sin(math.pi / 4))


def test_operating_point_at_zero_flow_is_quiet():
    op = operating_point(make_params(), 0.0, 0.0, 250, AMB)
    assert op.plate_dp_pa == 0 and op.p1_pa == 0 and op.stalled


# --------------------------------------------------------------------------- heat reuse (inside the kiln, before the plate)
def test_plate_sees_gas_already_cooled_by_the_reuse_tunnels():
    p = make_params({"reuse_extraction": 0.3})
    op = solve_steady(p, 0, 250, AMB)
    assert op.t_kiln_c == 250
    assert op.t_plate_c == pytest.approx(250 - 0.3 * (250 - AMB))
    assert plate_temperature(p, 250, AMB) == op.t_plate_c


def test_no_reuse_means_plate_temperature_equals_kiln_temperature():
    op = solve_steady(make_params({"reuse_extraction": 0}), 0, 250, AMB)
    assert op.t_plate_c == pytest.approx(250)


def test_more_heat_reuse_lowers_draft_and_natural_flow():
    little = solve_steady(make_params({"reuse_extraction": 0.05}), 0, 250, AMB)
    much = solve_steady(make_params({"reuse_extraction": 0.5}), 0, 250, AMB)
    assert much.t_chimney_mean_c < little.t_chimney_mean_c
    assert much.draft_pa < little.draft_pa and much.q_m3_s < little.q_m3_s


def test_reuse_tunnel_loss_shows_up_in_p1_not_in_the_plate_dp_at_equal_flow():
    """The tunnels are upstream of the plate: their loss deepens the suction at P1 and P2 together."""
    base = solve_steady(make_params({"k_reuse": 0}), 800, 250, AMB)
    leaky = solve_steady(make_params({"k_reuse": 10}), 800, 250, AMB)
    assert leaky.q_m3_s < base.q_m3_s                       # more resistance, less flow
    # at the SAME mass flow the plate dP is unchanged and only P1 moves
    same_flow = operating_point(make_params({"k_reuse": 10}), base.mass_flow_kg_s, 800, 250, AMB)
    assert same_flow.plate_dp_pa == pytest.approx(base.plate_dp_pa, rel=0.02)
    assert same_flow.p1_pa < base.p1_pa - 5


def test_fan_inlet_gas_is_at_plate_temperature():
    op = solve_steady(make_params({"reuse_extraction": 0.4}), 800, 250, AMB)
    assert op.t_chimney_top_c < op.t_plate_c                # chimney only cools further after the plate
