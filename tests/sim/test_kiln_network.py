import dataclasses
import math

import pytest

from sim.kiln.network import (solve_network, nominal_temperatures, couple_to_exhaust, damper_area_m2,
                              REFERENCE_SUCTION_PA)
from sim.kiln.params import KilnParams
from sim.kiln.schedule import (Schedule, kiln_state, ZONE_DAMPER, ZONE_PREHEATING, ZONE_FIRING, ZONE_COOLING,
                               ZONE_HANDLING, ZONE_PREDRYING)
from sim.params import make_params

AMB = 30.0


def solved(lead: float = 30.5, kp: KilnParams | None = None, schedule: Schedule | None = None, **kwargs):
    state = kiln_state(schedule or Schedule(), 0, start_lead=lead)
    return state, solve_network(state, kp or KilnParams(), nominal_temperatures(state, AMB), AMB, **kwargs)


# --------------------------------------------------------------------------- damper
def test_damper_area_grows_with_lift_and_is_limited_by_the_bore():
    kp = KilnParams()
    bore = math.pi / 4 * 0.45 ** 2
    areas = [damper_area_m2(kp, lift) for lift in (0, 1, 3, 9, 23.5)]
    assert areas[0] == 0.0
    assert areas == sorted(areas)
    assert areas[1] == pytest.approx(math.pi * 0.45 * 0.0254 * 0.7, rel=0.03)    # small lift: the curtain rules
    assert areas[4] < bore and areas[4] > 0.95 * bore                             # large lift: the bore rules


# --------------------------------------------------------------------------- conservation
def test_everything_that_enters_leaves_through_the_dampers():
    _, net = solved()
    assert sum(net.inlet_kg_s) == pytest.approx(net.total_kg_s, rel=1e-6)
    assert sum(net.damper_kg_s) == pytest.approx(net.total_kg_s)
    assert net.total_kg_s > 1.0


def test_mass_balances_at_every_unit():
    state, net = solved()
    for u in state.units:
        i = u.firebox.number - 1
        arriving = net.along_kg_s[i - 1] if not state.unit(u.firebox.number - 1).paper_sealed else 0.0
        balance = arriving + net.inlet_kg_s[i] - net.damper_kg_s[i] - net.along_kg_s[i]
        assert balance == pytest.approx(0.0, abs=1e-6), u.firebox.number


@pytest.mark.parametrize("lead", [3.2, 17.9, 30.5, 44.0, 58.7])
def test_solution_exists_wherever_the_fire_is(lead):
    _, net = solved(lead)
    assert net.iterations < 200
    assert 0.12 < net.equivalent_area_m2 < 0.25
    assert sum(net.inlet_kg_s) == pytest.approx(net.total_kg_s, rel=1e-6)


# --------------------------------------------------------------------------- shape of the flow
def test_suction_deepens_from_the_open_doors_to_the_dampers():
    state, net = solved()
    walk = [u for u in sorted(state.units, key=lambda u: u.ahead_ru)
            if u.zone in (ZONE_COOLING, ZONE_FIRING, ZONE_PREHEATING, ZONE_DAMPER)]
    pressures = [net.pressure_pa[u.firebox.number - 1] for u in walk]
    assert pressures == sorted(pressures, reverse=True)
    assert pressures[0] > -5 and pressures[-1] < -80
    handling = [net.pressure_pa[u.firebox.number - 1] for u in state.in_zone(ZONE_HANDLING)]
    assert all(abs(p) < 1.0 for p in handling)                 # open doors: room pressure


def test_gas_flows_clockwise_through_the_fire():
    state, net = solved()
    for zone in (ZONE_COOLING, ZONE_FIRING, ZONE_PREHEATING):
        assert all(net.along_kg_s[u.firebox.number - 1] > 0.5 * net.total_kg_s for u in state.in_zone(zone))


def test_flow_builds_from_zero_to_full_across_the_damper_zone():
    """Head of the damper zone carries nothing; the unit next to pre-heating carries nearly everything."""
    state, net = solved()
    zone = sorted(state.in_zone(ZONE_DAMPER), key=lambda u: u.ahead_ru)        # nearest the fire first
    through = [net.along_kg_s[u.firebox.number - 1] for u in zone]
    leak_allowance = 0.01 * net.total_kg_s                    # each unit also leaks a little air in
    assert all(later <= earlier + leak_allowance for earlier, later in zip(through, through[1:]))
    assert abs(through[-1]) < 0.02 * net.total_kg_s
    feeding = net.along_kg_s[zone[0].firebox.number - 2]                        # arriving from pre-heating
    assert feeding > 0.95 * net.total_kg_s


def test_lifted_dampers_share_the_flow_roughly_equally():
    state, net = solved()
    full = [u for u in state.lifted_dampers if u.damper_lift_in == 9.0]
    shares = [net.damper_kg_s[u.firebox.number - 1] / net.total_kg_s for u in full]
    assert len(full) == 3
    assert all(0.18 < s < 0.30 for s in shares)
    assert all(net.damper_kg_s[u.firebox.number - 1] == 0 for u in state.units if u.damper_lift_in == 0)


def test_paper_seal_stops_air_coming_in_the_wrong_way():
    state, net = solved()
    sealed = next(u for u in state.units if u.paper_sealed)
    assert sealed.zone == ZONE_PREDRYING
    assert net.along_kg_s[sealed.firebox.number - 1] == 0.0
    assert net.pressure_pa[sealed.firebox.number - 1] < -80                    # it sits at damper-zone suction
    assert abs(net.pressure_pa[sealed.firebox.number % 60]) < 1.0              # the far side is at room pressure


def test_most_air_enters_at_the_doors_nearest_the_fire():
    state, net = solved()
    part_open = [u for u in state.units if u.door == "part-open"]
    assert part_open
    doors = sum(net.inlet_kg_s[u.firebox.number - 1] for u in state.units if u.door != "closed")
    assert doors > 0.85 * net.total_kg_s                                       # the rest is leakage
    assert all(net.inlet_kg_s[u.firebox.number - 1] > 0 for u in part_open)


# --------------------------------------------------------------------------- scaling
def test_flows_scale_with_the_square_root_of_suction():
    _, net = solved()
    assert net.suction_pa == REFERENCE_SUCTION_PA
    four_times = net.scaled(4 * REFERENCE_SUCTION_PA)
    assert four_times.total_kg_s == pytest.approx(2 * net.total_kg_s)
    assert four_times.pressure_pa[35] == pytest.approx(4 * net.pressure_pa[35])
    assert four_times.equivalent_area_m2 == net.equivalent_area_m2
    assert net.scaled(0).total_kg_s == 0.0


# --------------------------------------------------------------------------- what changes the resistance
def test_tighter_tile_setting_makes_the_kiln_harder_to_pull_through():
    _, normal = solved()
    _, tight = solved(kp=dataclasses.replace(KilnParams(), setting_free_area_m2=0.8))
    assert tight.equivalent_area_m2 < 0.7 * normal.equivalent_area_m2


def test_lower_damper_peak_makes_the_kiln_harder_to_pull_through():
    _, normal = solved()
    _, low = solved(schedule=Schedule(damper_max_in=2.0, damper_raise_in_h=3.6, damper_lower_in_h=2.0))
    assert low.equivalent_area_m2 < normal.equivalent_area_m2


def test_open_portholes_let_extra_air_in_at_the_firing_units():
    state, closed = solved()
    firing = frozenset(u.firebox.number for u in state.in_zone(ZONE_FIRING))
    _, charging = solved(charging_units=firing)
    assert charging.equivalent_area_m2 > closed.equivalent_area_m2
    index = min(firing) - 1
    assert charging.inlet_kg_s[index] > 5 * closed.inlet_kg_s[index]


def test_no_lifted_damper_means_no_flow():
    state = kiln_state(Schedule(), 0, start_lead=30.5)
    shut = dataclasses.replace(state, units=tuple(dataclasses.replace(u, damper_lift_in=0.0) for u in state.units))
    net = solve_network(shut, KilnParams(), nominal_temperatures(shut, AMB), AMB)
    assert net.total_kg_s == 0.0 and net.equivalent_area_m2 == 0.0
    assert net.t_exhaust_c == AMB


# --------------------------------------------------------------------------- temperatures
def test_nominal_temperatures_are_hot_at_the_fire_and_cool_at_the_dampers():
    state = kiln_state(Schedule(), 0, start_lead=30.5)
    temps = nominal_temperatures(state, AMB)
    by_zone = {zone: [temps[u.firebox.number - 1] for u in state.in_zone(zone)]
               for zone in (ZONE_FIRING, ZONE_DAMPER, ZONE_HANDLING, ZONE_COOLING)}
    assert max(by_zone[ZONE_FIRING]) == pytest.approx(900)
    assert all(t == 130 for t in by_zone[ZONE_DAMPER])
    assert all(t < 50 for t in by_zone[ZONE_HANDLING])
    assert min(by_zone[ZONE_COOLING]) < 100 < max(by_zone[ZONE_COOLING])


def test_exhaust_temperature_is_the_mix_of_what_the_dampers_take():
    state = kiln_state(Schedule(), 0, start_lead=30.5)
    temps = nominal_temperatures(state, AMB)
    hottest = max(state.lifted_dampers, key=lambda u: u.damper_lift_in).firebox.number - 1
    temps[hottest] = 300.0
    net = solve_network(state, KilnParams(), temps, AMB)
    assert 130 < net.t_exhaust_c < 300
    expected = sum(m * t for m, t in zip(net.damper_kg_s, temps)) / net.total_kg_s
    assert net.t_exhaust_c == pytest.approx(expected)


# --------------------------------------------------------------------------- joined to the fan and chimney
def test_kiln_joined_to_stage_1_reproduces_the_site_operating_point():
    _, net = solved()
    op, scaled = couple_to_exhaust(make_params(), net, 380.0, AMB)
    assert scaled.total_kg_s == pytest.approx(op.mass_flow_kg_s, rel=1e-6)     # one flow through kiln and fan
    assert scaled.suction_pa == pytest.approx(-op.p_fan_in_pa)
    assert op.p1_pa == pytest.approx(119.2, abs=10) and op.p2_pa == pytest.approx(87.0, abs=10)
    assert op.p_top_residual_pa == pytest.approx(0.0, abs=1e-6)


def test_faster_fan_pulls_more_through_every_damper():
    state, net = solved()
    _, slow = couple_to_exhaust(make_params(), net, 300.0, AMB)
    _, fast = couple_to_exhaust(make_params(), net, 450.0, AMB)
    for u in state.lifted_dampers:
        i = u.firebox.number - 1
        assert fast.damper_kg_s[i] > slow.damper_kg_s[i] > 0
    assert fast.suction_pa > slow.suction_pa


def test_tighter_kiln_means_more_suction_and_less_flow_at_the_same_fan_speed():
    _, normal = solved()
    _, tight = solved(kp=dataclasses.replace(KilnParams(), setting_free_area_m2=1.0))
    op_normal, _ = couple_to_exhaust(make_params(), normal, 380.0, AMB)
    op_tight, _ = couple_to_exhaust(make_params(), tight, 380.0, AMB)
    assert op_tight.q_m3_s < op_normal.q_m3_s
    assert op_tight.p_fan_in_pa < op_normal.p_fan_in_pa
