import math

import pytest

from sim.gas import density, barometric_pressure, air_viscosity, AIR_MOLAR_MASS_G_MOL, G
from sim.instruments import estimate_flow
from sim.params import make_params
from sim.plant import (Plant, solve_steady, operating_point, environment, chimney_state,
                       chimney_geometry, _loss_coefficients, PERMANENT_LOSS_EXPONENT, CHIMNEY_SLICES)

AMB = 30.0
GAS = 130.0
RATED = 380.0
FT = 0.3048


def no_draft_params(**overrides):
    """Gas as warm and as heavy as the outside air: no buoyancy, so only the fan drives flow."""
    return make_params({"t_gas_c": AMB, "t_amb_c": AMB, "gas_molar_mass_g_mol": AIR_MOLAR_MASS_G_MOL,
                        **overrides})


# --------------------------------------------------------------------------- gas
def test_density_ideal_gas_air_at_20c():
    assert density(101325, 20, 28.96) == pytest.approx(1.204, abs=0.002)


def test_hotter_gas_is_lighter():
    assert density(101325, 300, 28.5) < density(101325, 100, 28.5)


def test_air_pressure_at_chimney_top_matches_the_hand_value():
    drop = 101325 - barometric_pressure(101325, 38.1, 25)
    assert drop == pytest.approx(441, abs=3)            # rho*g*h = 1.184 * 9.807 * 38.1


def test_air_pressure_is_unchanged_at_ground_level_and_falls_with_height():
    assert barometric_pressure(101325, 0, 25) == pytest.approx(101325)
    assert barometric_pressure(101325, 60, 25) < barometric_pressure(101325, 30, 25)


def test_air_viscosity_matches_table_values():
    assert air_viscosity(20) == pytest.approx(1.81e-5, rel=0.01)
    assert air_viscosity(130) > air_viscosity(20)       # gases get more viscous when hot


# --------------------------------------------------------------------------- chimney geometry
def test_default_chimney_is_the_owners_125_ft_tapered_stack():
    p = make_params()
    assert p.chimney_height_m == pytest.approx(125 * FT)
    assert p.chimney_bottom_side_m == pytest.approx(5 * FT)
    assert p.chimney_top_side_m == pytest.approx(3 * FT, abs=0.001)


def test_chimney_slices_taper_linearly_from_base_to_top():
    dz, z_mid, sides = chimney_geometry(40.0, 2.0, 1.0)
    assert len(sides) == CHIMNEY_SLICES and dz == pytest.approx(2.0)
    assert z_mid[0] == pytest.approx(1.0) and z_mid[-1] == pytest.approx(39.0)
    assert sides[0] == pytest.approx(2.0 - 1.0 / 40) and sides[-1] == pytest.approx(1.0 + 1.0 / 40)
    assert all(a > b for a, b in zip(sides, sides[1:]))


def test_outside_air_is_thinner_at_the_top_of_the_chimney():
    state = chimney_state(make_params(), 3.0, GAS, AMB)
    assert state.rho_outside[-1] < state.rho_outside[0]
    assert state.p_outside_abs[-1] < state.p_outside_abs[0]
    assert all(g < o for g, o in zip(state.rho_gas, state.rho_outside))     # hot gas is lighter all the way up


def test_straight_chimney_matches_the_single_lump_formula():
    """With no taper and no wall loss the slice sum is the textbook g*H*(rho_out - rho_gas)."""
    p = make_params({"chimney_top_side_m": 1.2, "chimney_bottom_side_m": 1.2, "chimney_u_w_m2k": 0})
    state = chimney_state(p, 3.0, GAS, AMB)
    lump = G * p.chimney_height_m * (density(p.p_atm_pa, AMB, AIR_MOLAR_MASS_G_MOL)
                                     - density(p.p_atm_pa, GAS, p.gas_molar_mass_g_mol))
    assert state.draft_pa == pytest.approx(lump, rel=0.005)
    assert state.t_top_c == pytest.approx(GAS)
    k_friction_lump = p.chimney_friction * p.chimney_height_m / (2 * 1.2 ** 5 * state.rho_gas[0])
    assert state.k_friction == pytest.approx(k_friction_lump, rel=0.005)


def test_slice_count_hardly_changes_the_answer():
    p = make_params()
    coarse = chimney_state(p, 3.0, GAS, AMB, slices=10)
    fine = chimney_state(p, 3.0, GAS, AMB, slices=80)
    assert coarse.draft_pa == pytest.approx(fine.draft_pa, rel=0.002)
    assert coarse.k_friction == pytest.approx(fine.k_friction, rel=0.02)
    assert coarse.t_top_c == pytest.approx(fine.t_top_c, abs=0.2)


def test_narrower_top_raises_exit_loss_and_lowers_flow():
    wide = solve_steady(make_params({"chimney_top_side_m": 1.5}), RATED, GAS, AMB)
    narrow = solve_steady(make_params({"chimney_top_side_m": 0.5}), RATED, GAS, AMB)
    assert narrow.loss_exit_pa > 10 * wide.loss_exit_pa
    assert narrow.q_m3_s < wide.q_m3_s


def test_exit_loss_is_one_velocity_head_at_the_top_opening():
    p = make_params()
    op = solve_steady(p, RATED, GAS, AMB)
    state = chimney_state(p, op.mass_flow_kg_s, GAS, AMB)
    v_exit = op.mass_flow_kg_s / (state.rho_top * p.chimney_top_side_m ** 2)
    assert op.loss_exit_pa == pytest.approx(state.rho_top * v_exit ** 2 / 2)


# --------------------------------------------------------------------------- natural draft
def test_no_draft_and_no_flow_without_fan_when_gas_matches_ambient():
    op = solve_steady(no_draft_params(), rpm=0, t_gas_c=AMB, t_amb_c=AMB)
    assert op.draft_pa == pytest.approx(0.0, abs=1e-9)
    assert op.q_m3_s == 0.0 and op.stalled


def test_hot_gas_flows_by_natural_draft_alone():
    op = solve_steady(make_params(), rpm=0, t_gas_c=GAS, t_amb_c=AMB)
    assert op.draft_pa > 50
    assert op.q_m3_s > 1.0 and not op.stalled


def test_draft_grows_with_chimney_height():
    low = solve_steady(make_params({"chimney_height_m": 20}), 0, GAS, AMB)
    high = solve_steady(make_params({"chimney_height_m": 40}), 0, GAS, AMB)
    assert high.draft_pa > low.draft_pa
    assert high.q_m3_s > low.q_m3_s


def test_draft_grows_with_gas_temperature():
    cool = solve_steady(make_params(), 0, 90, AMB)
    hot = solve_steady(make_params(), 0, 250, AMB)
    assert hot.draft_pa > cool.draft_pa and hot.q_m3_s > cool.q_m3_s


def test_cold_weather_increases_draft():
    warm = solve_steady(make_params(), 0, GAS, 40)
    cold = solve_steady(make_params(), 0, GAS, 5)
    assert cold.draft_pa > warm.draft_pa


def test_chimney_wall_losses_reduce_draft():
    insulated = solve_steady(make_params({"chimney_u_w_m2k": 0}), 0, GAS, AMB)
    leaky = solve_steady(make_params({"chimney_u_w_m2k": 15}), 0, GAS, AMB)
    assert leaky.t_chimney_mean_c < insulated.t_chimney_mean_c
    assert leaky.draft_pa < insulated.draft_pa


def test_gas_cools_less_at_higher_flow():
    p = make_params()
    slow = solve_steady(p, 0, GAS, AMB)
    fast = solve_steady(p, 450, GAS, AMB)
    assert fast.t_chimney_mean_c > slow.t_chimney_mean_c
    assert fast.t_chimney_top_c > slow.t_chimney_top_c
    assert fast.t_chimney_top_c < GAS


def reversed_draft_params():
    """Gas clearly colder than the air outside (and equally heavy per mole): the stack pushes backwards."""
    return make_params({"t_amb_c": 45, "t_gas_c": 25, "gas_molar_mass_g_mol": AIR_MOLAR_MASS_G_MOL})


def test_draft_can_reverse_and_flow_stalls_without_fan():
    op = solve_steady(reversed_draft_params(), 0, 25, 45)
    assert op.draft_pa < 0
    assert op.stalled and op.q_m3_s == 0.0


def test_fan_overcomes_reversed_draft():
    assert solve_steady(reversed_draft_params(), RATED, 25, 45).q_m3_s > 0.5


# --------------------------------------------------------------------------- fan
def test_flow_rises_monotonically_with_fan_speed():
    p = make_params()
    flows = [solve_steady(p, rpm, GAS, AMB).q_m3_s for rpm in (0, 100, 200, 300, 380, 450)]
    assert flows == sorted(flows) and flows[-1] > flows[0]


def test_flow_proportional_to_speed_when_there_is_no_draft():
    p = no_draft_params()
    q200 = solve_steady(p, 200, AMB, AMB).q_m3_s
    q400 = solve_steady(p, 400, AMB, AMB).q_m3_s
    assert q400 / q200 == pytest.approx(2.0, rel=1e-6)   # affinity law Q ~ N


def test_fan_adds_less_flow_when_natural_draft_is_strong():
    """The core property of this system: the fan's effect depends on the draft already present."""
    hot_kiln = make_params()
    gain_no_draft = (solve_steady(no_draft_params(), RATED, AMB, AMB).q_m3_s
                     - solve_steady(no_draft_params(), 0, AMB, AMB).q_m3_s)
    gain_with_draft = (solve_steady(hot_kiln, RATED, 250, AMB).q_m3_s
                       - solve_steady(hot_kiln, 0, 250, AMB).q_m3_s)
    assert gain_with_draft < gain_no_draft


def test_stopped_fan_is_a_small_restriction_not_a_blockage():
    op = solve_steady(make_params(), 0, GAS, AMB)
    assert op.fan_dp_pa < 0                      # drag, no pressure added
    assert op.q_m3_s > 1.0                       # but flow still passes


def test_warm_start_guess_does_not_change_the_answer():
    p = make_params()
    cold = solve_steady(p, RATED, GAS, AMB)
    warm = solve_steady(p, RATED, GAS, AMB, guess=0.3)
    assert warm.mass_flow_kg_s == pytest.approx(cold.mass_flow_kg_s, rel=1e-8)


# --------------------------------------------------------------------------- balance and plate
@pytest.mark.parametrize("rpm", [0, 150, 380, 450])
def test_pressure_balance_closes_at_steady_state(rpm):
    op = solve_steady(make_params({"kiln_gauge_pa": 5}), rpm, GAS, AMB)
    losses = (op.loss_kiln_pa + op.loss_fan_to_plate_pa + op.loss_plate_permanent_pa
              + op.loss_restriction_pa + op.loss_chimney_friction_pa + op.loss_exit_pa)
    assert 5 + op.draft_pa + op.fan_dp_pa - losses == pytest.approx(0.0, abs=1e-6)
    assert op.p_top_residual_pa == pytest.approx(0.0, abs=1e-6)


def test_pressure_walk_follows_the_station_order():
    """kiln -> fan inlet (suction) -> fan outlet -> P1 -> P2 -> chimney base."""
    op = solve_steady(make_params(), RATED, GAS, AMB)
    assert op.p_fan_in_pa == pytest.approx(-op.loss_kiln_pa)
    assert op.p_fan_in_pa < 0 < op.p_fan_out_pa
    assert op.p_fan_out_pa - op.p_fan_in_pa == pytest.approx(op.fan_dp_pa)
    assert op.p1_pa == pytest.approx(op.p_fan_out_pa - op.loss_fan_to_plate_pa)
    assert op.p1_pa - op.p2_pa == pytest.approx(op.plate_dp_pa)
    assert op.p_chimney_base_pa == pytest.approx(op.p1_pa - op.loss_plate_permanent_pa - op.loss_restriction_pa)
    assert op.p2_pa < op.p1_pa


def test_plate_pressures_are_negative_on_draft_alone_and_rise_with_fan_speed():
    """The plate is on the fan's discharge side: draft pulls it negative, the fan pushes it positive."""
    p = make_params()
    stopped = solve_steady(p, 0, GAS, AMB)
    running = solve_steady(p, RATED, GAS, AMB)
    assert stopped.p1_pa < 0 and stopped.p2_pa < 0
    assert running.p1_pa > 0 and running.p2_pa > 0
    p1 = [solve_steady(p, rpm, GAS, AMB).p1_pa for rpm in (0, 150, 300, 450)]
    assert p1 == sorted(p1)


def test_default_case_lands_near_the_site_operating_point():
    """Site reading (LabVIEW screen, 17-03-2026): P1 119.2 Pa, P2 87 Pa at 130.4 degC and 380 rpm."""
    op = solve_steady(make_params(), 380, 130.4, 30)
    assert op.p1_pa == pytest.approx(119.2, abs=6)
    assert op.p2_pa == pytest.approx(87.0, abs=6)


def test_chimney_base_stays_under_suction_when_the_restriction_is_removed():
    op = solve_steady(make_params({"restriction_free_area_m2": 3.0}), RATED, GAS, AMB)
    assert op.loss_restriction_pa < 2.0
    assert op.p2_pa < 0                          # only the chimney is downstream, and it pulls


def test_kiln_gauge_pressure_pushes_gas_through():
    base = solve_steady(make_params(), RATED, GAS, AMB)
    pushed = solve_steady(make_params({"kiln_gauge_pa": 20}), RATED, GAS, AMB)
    assert pushed.q_m3_s > base.q_m3_s
    assert pushed.p1_pa > base.p1_pa


def test_tighter_kiln_deepens_fan_suction_and_lowers_flow():
    open_kiln = solve_steady(make_params({"kiln_free_area_m2": 0.3}), RATED, GAS, AMB)
    tight_kiln = solve_steady(make_params({"kiln_free_area_m2": 0.1}), RATED, GAS, AMB)
    assert tight_kiln.q_m3_s < open_kiln.q_m3_s
    assert tight_kiln.p_fan_in_pa < open_kiln.p_fan_in_pa


def test_kiln_loss_is_the_velocity_head_through_its_free_area():
    p = make_params()
    op = solve_steady(p, RATED, GAS, AMB)
    velocity = op.q_m3_s / p.kiln_free_area_m2
    assert op.loss_kiln_pa == pytest.approx(op.rho_plate * velocity ** 2 / 2)


def test_plate_dp_scales_with_flow_squared():
    p = make_params()
    ratios = []
    for rpm in (0, 250, 450):
        op = solve_steady(p, rpm, GAS, AMB)
        ratios.append(op.plate_dp_pa / op.q_m3_s ** 2)
    assert ratios == pytest.approx([ratios[0]] * 3, rel=1e-9)


def test_smaller_plate_bore_gives_bigger_dp_and_less_flow():
    open_plate = solve_steady(make_params({"plate_beta": 0.7}), RATED, GAS, AMB)
    tight_plate = solve_steady(make_params({"plate_beta": 0.4}), RATED, GAS, AMB)
    assert tight_plate.plate_dp_pa > open_plate.plate_dp_pa
    assert tight_plate.q_m3_s < open_plate.q_m3_s


def test_permanent_loss_exponent_is_the_documented_one():
    assert PERMANENT_LOSS_EXPONENT == 1.9
    k = _loss_coefficients(make_params({"plate_beta": 0.6}))
    assert k.k_plate_loop == pytest.approx(k.k_plate_full * (1 - 0.6 ** 1.9))


# --------------------------------------------------------------------------- flow estimate
def test_estimator_recovers_true_flow_when_assumptions_are_right():
    p = make_params()
    op = solve_steady(p, RATED, GAS, AMB)
    assert estimate_flow(p, op.p1_pa, op.p2_pa, op.t_gas_c) == pytest.approx(op.q_m3_s, rel=1e-9)


def test_estimator_cd_error_scales_the_estimate():
    base = make_params()
    wrong = make_params({"est_cd_error_pct": 5})
    op = solve_steady(base, RATED, GAS, AMB)
    ratio = (estimate_flow(wrong, op.p1_pa, op.p2_pa, GAS) / estimate_flow(base, op.p1_pa, op.p2_pa, GAS))
    assert ratio == pytest.approx(1.05)


def test_estimator_heavier_assumed_gas_reads_low():
    base = make_params()
    heavy = make_params({"est_molar_mass_g_mol": 31})
    op = solve_steady(base, RATED, GAS, AMB)
    assert estimate_flow(heavy, op.p1_pa, op.p2_pa, GAS) < estimate_flow(base, op.p1_pa, op.p2_pa, GAS)


def test_estimator_returns_zero_for_no_or_negative_dp():
    p = make_params()
    assert estimate_flow(p, -10, -10, GAS) == 0.0
    assert estimate_flow(p, -20, -10, GAS) == 0.0


# --------------------------------------------------------------------------- dynamics
def test_plant_starts_at_steady_state():
    p = make_params()
    plant = Plant(p, RATED, GAS, AMB)
    op = plant.step(0.1, RATED, GAS, AMB)
    assert op.q_m3_s == pytest.approx(solve_steady(p, RATED, GAS, AMB).q_m3_s, rel=1e-3)
    assert op.p_top_residual_pa == pytest.approx(0.0, abs=0.5)


def test_step_response_rises_smoothly_to_the_new_steady_state():
    p = make_params()
    plant = Plant(p, 220, GAS, AMB)
    flows = [plant.step(0.5, 450, GAS, AMB).q_m3_s for _ in range(240)]    # 120 s
    assert all(b >= a - 1e-12 for a, b in zip(flows, flows[1:]))           # no overshoot or wobble
    assert flows[-1] == pytest.approx(solve_steady(p, 450, GAS, AMB).q_m3_s, rel=0.01)


def test_drive_ramp_limits_how_fast_speed_can_change():
    p = make_params({"drive_ramp_rpm_s": 100, "motor_tau_s": 0.1})
    plant = Plant(p, 220, GAS, AMB)
    for _ in range(10):
        plant.step(0.1, 450, GAS, AMB)        # 1 s of simulated time
    assert plant.rpm <= 220 + 100 * 1.0 + 1e-6


def test_gas_temperature_lags_the_kiln():
    p = make_params({"gas_temp_tau_s": 60})
    plant = Plant(p, RATED, 100, AMB)
    for _ in range(60):
        plant.step(1.0, RATED, 200, AMB)       # 60 s = one time constant
    assert plant.t_gas_c == pytest.approx(100 + 100 * (1 - math.exp(-1)), abs=0.5)


def test_environment_swings_around_the_base_values():
    p = make_params({"t_amb_swing_k": 10, "t_amb_period_s": 400, "t_gas_swing_k": 40, "t_gas_period_s": 800})
    amb0, gas0 = environment(p, 0)
    amb_q, gas_q = environment(p, 100)         # quarter of the ambient period / eighth of the gas period
    assert amb0 == pytest.approx(30.0) and gas0 == pytest.approx(130.0)
    assert amb_q == pytest.approx(40.0)
    assert gas_q == pytest.approx(130 + 40 * math.sin(math.pi / 4))


def test_operating_point_at_zero_flow_is_quiet():
    op = operating_point(make_params(), 0.0, 0.0, GAS, AMB)
    assert op.plate_dp_pa == 0 and op.p1_pa == 0 and op.stalled
