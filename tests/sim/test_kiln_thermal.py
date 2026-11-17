"""
Tests for the kiln heat, fuel and drying model (build stage H).

The heat-transfer numbers are tuned placeholders, so the plant-like checks use generous bands. The
balances are checked tightly: they hold by construction, whatever the parameters.
"""
import dataclasses
import math

import pytest

from sim.kiln.fuel import (burn, charge_mass_kg, charge_plan, lhv_j_kg, moisture_factor, dry_lhv_mj_kg)
from sim.kiln.kilnsim import KilnSim
from sim.kiln.params import KilnParams
from sim.kiln.schedule import Schedule, ZONE_FIRING, ZONE_PREHEATING, ZONE_HANDLING
from sim.kiln.thermal import GasFlows, Solids, thermal_step, flow_order, stored_heat_j

DAY_S = 86400.0
COARSE_DT = 300.0


def run(sim: KilnSim, hours: float) -> list[dict]:
    return [sim.step() for _ in range(round(hours * 3600.0 / sim.dt_s))]


@pytest.fixture(scope="module")
def two_days():
    """The default kiln run for two days at a 300 s step, with checks collected at every step."""
    sim = KilnSim(dt_s=COARSE_DT)
    kp = sim.kp
    records, wet_when_firing, hot_while_wet, drying_seen = [], 0.0, [], 0
    point_at = {}
    for _ in range(round(2 * DAY_S / COARSE_DT)):
        records.append(sim.step())
        for i, u in enumerate(sim.last_state.units):
            water = sim.solids.water_kg[i]
            if u.zone == ZONE_FIRING:
                wet_when_firing = max(wet_when_firing, water)
            if water > 0.0:
                hot_while_wet.append(sim.solids.tile_c[i])
                if water < kp.tile_water_kg:
                    drying_seen += 1
        if sim.time_s in (DAY_S, 2 * DAY_S):
            point_at[sim.time_s] = list(sim.point_c)
    return dict(sim=sim, records=records, wet_when_firing=wet_when_firing, hot_while_wet=hot_while_wet,
                drying_seen=drying_seen, point_at=point_at)


# --------------------------------------------------------------------------- balances
def test_energy_balance_closes_over_a_run(two_days):
    e = two_days["sim"].energy_balance()
    assert e["fuel"] > 1e11                                           # about 1 MW for two days
    heat_out = e["stored_change"] + e["exhaust"] + e["wall"] + e["latent"] + e["tiles_out"] + e["vented"]
    assert e["fuel"] + e["air_in"] + e["tiles_in"] == pytest.approx(heat_out, rel=1e-9)
    assert abs(e["relative_error"]) < 1e-9
    assert e["air_in"] == 0.0                                         # constant ambient = the reference
    assert e["latent"] > 0.05 * e["fuel"] and e["exhaust"] > 0.2 * e["fuel"]


def test_mass_balance_every_step(two_days):
    """Gas reaching the main flue (plus any vented) = air in + water vapour + fuel burnt."""
    for r in two_days["records"]:
        made = r["air_in_kg_s"] + r["vapour_kg_s"] + r["fuel_burnt_kg_s"]
        assert r["exhaust_kg_s"] + r["vented_kg_s"] == pytest.approx(made, rel=1e-9)
        assert r["fuel_burnt_kg_s"] > 0.0 and r["vented_kg_s"] < 0.01 * r["exhaust_kg_s"]


def test_thermal_step_conserves_energy_on_a_small_chain():
    kp = KilnParams()
    flows = GasFlows(along_kg_s=(1.0, 1.2, 0.0), inlet_kg_s=(1.0, 0.2, 0.0), damper_kg_s=(0.0, 0.0, 1.2))
    solids = Solids(tile_c=[50.0, 400.0, 99.0], brick_c=[60.0, 500.0, 120.0], water_kg=[0.0, 0.0, 300.0],
                    has_tiles=[True, True, True])
    before = stored_heat_j(kp, solids, 30.0)
    dt = 600.0
    r = thermal_step(kp, flows, solids, fuel_w=[0.0, 2e5, 0.0], fuel_kg_s=[0.0, 0.014, 0.0], t_amb_c=30.0,
                     t_ref_c=30.0, dt_s=dt)
    stored = stored_heat_j(kp, solids, 30.0) - before
    assert r.fuel_w * dt == pytest.approx(stored + (r.exhaust_w + r.wall_loss_w + r.latent_w + r.vented_w) * dt, rel=1e-12)
    assert r.exhaust_kg_s == pytest.approx(1.2 + 0.014 + r.vapour_kg_s)
    assert r.vapour_kg_s > 0.0 and solids.water_kg[2] < 300.0


# --------------------------------------------------------------------------- plant-like behaviour
def test_standard_plan_gives_a_plant_like_peak_and_exhaust(two_days):
    second_day = [r for r in two_days["records"] if r["time_s"] > DAY_S]
    assert all(750.0 < r["peak_point_c"] < 1050.0 for r in second_day)
    exhaust = sum(r["t_exhaust_c"] for r in second_day) / len(second_day)
    assert 100.0 < exhaust < 180.0
    heat = sum(r["heat_release_kw"] for r in second_day) / len(second_day)
    assert 800.0 < heat < 1300.0                                      # about 15 fireboxes x 72 kW
    assert all(r["firing_units"] in (15, 16) for r in second_day)


def test_fan_sees_a_site_like_operating_point(two_days):
    last = two_days["records"][-1]
    assert last["rpm"] == 380.0
    assert 90.0 < last["p1_pa"] < 170.0 and 60.0 < last["p2_pa"] < 140.0     # site: 119 and 87 Pa (gauge)
    assert last["p1_pa"] > last["p2_pa"]
    assert 2.5 < last["exhaust_kg_s"] < 4.5


def test_hottest_unit_travels_at_the_scheduled_rate(two_days):
    points = two_days["point_at"]
    first = max(range(60), key=lambda i: points[DAY_S][i])
    second = max(range(60), key=lambda i: points[2 * DAY_S][i])
    assert 7 <= (second - first) % 60 <= 11                           # schedule: 9 room units per day


def test_tiles_hold_at_boiling_until_dry_and_are_dry_before_firing(two_days):
    kp = two_days["sim"].kp
    assert two_days["drying_seen"] > 0
    assert max(two_days["hot_while_wet"]) <= kp.boiling_c + 1e-9
    assert two_days["wet_when_firing"] == 0.0
    drying = [u for u in two_days["sim"].snapshot()["units"] if 0.0 < u["water_kg"] < kp.tile_water_kg]
    assert drying and all(u["tile_c"] == pytest.approx(kp.boiling_c) for u in drying)


def test_tiles_are_replaced_in_the_handling_zone(two_days):
    sim = two_days["sim"]
    assert sim.energy["tiles_out"] > 0.0
    reloaded = [i for i, u in enumerate(sim.last_state.units)
                if u.zone == ZONE_HANDLING and sim.fresh[i] and sim.solids.has_tiles[i]]
    assert reloaded
    assert all(sim.solids.water_kg[i] > 0.0 for i in reloaded)


# --------------------------------------------------------------------------- fuel and its rules
def test_firing_plan_totals_and_shape():
    kp = KilnParams()
    plan = charge_plan(kp, 160)
    assert len(plan) == 160 and sum(plan) == pytest.approx(724.0)
    assert plan[0] < plan[80] > plan[-1]
    assert plan[0] == pytest.approx(kp.ramp_start_fraction * plan[80])


def test_heating_value_and_moisture_adjustment():
    kp = KilnParams()
    assert lhv_j_kg(kp, 0.22) == pytest.approx(14.3e6)
    assert 18.0 < dry_lhv_mj_kg(kp) < 20.0
    assert lhv_j_kg(kp, 0.35) < lhv_j_kg(kp, 0.22)
    assert moisture_factor(kp, 0.22) == pytest.approx(1.0)
    wet = moisture_factor(kp, 0.35)
    assert wet > 1.0 and wet * lhv_j_kg(kp, 0.35) == pytest.approx(lhv_j_kg(kp, 0.22))   # same heat per charge
    none = dataclasses.replace(kp, moisture_compensation=0.0)
    assert moisture_factor(none, 0.35) == 1.0


def test_conditional_charges():
    kp = KilnParams()
    plan = charge_plan(kp, 160)
    assert charge_mass_kg(kp, plan, 100, kp.skip_above_c + 1, 0.22) == (0.0, "skip")
    normal, reason = charge_mass_kg(kp, plan, 100, 800.0, 0.22)
    assert reason == "plan" and normal == pytest.approx(plan[99])
    more, reason = charge_mass_kg(kp, plan, 100, kp.add_below_c - 1, 0.22)
    assert reason == "add" and more == pytest.approx(plan[99] + kp.add_kg)
    early, reason = charge_mass_kg(kp, plan, 5, kp.add_below_c - 1, 0.22)          # before the ramp ends
    assert reason == "plan" and early == pytest.approx(plan[4])


def test_conditional_charge_skips_fuel_on_a_hot_kiln():
    hot_rule = KilnSim(kp=dataclasses.replace(KilnParams(), skip_above_c=600.0), dt_s=COARSE_DT)
    normal = KilnSim(dt_s=COARSE_DT)
    fed_hot = sum(r["fuel_fed_kg"] for r in run(hot_rule, 3))
    fed_normal = sum(r["fuel_fed_kg"] for r in run(normal, 3))
    assert fed_hot < 0.8 * fed_normal
    assert "skip" in hot_rule.last_reason


def test_a_charge_burns_out_exponentially_for_any_step():
    one = burn(4.5, 4.5 * 14.3e6, 300.0, 240.0)
    half = burn(4.5, 4.5 * 14.3e6, 150.0, 240.0)
    two = burn(half[2], half[3], 150.0, 240.0)
    assert one[2] == pytest.approx(two[2]) and one[0] == pytest.approx(half[0] + two[0])
    assert one[0] == pytest.approx(4.5 * (1.0 - math.exp(-300.0 / 240.0)))
    assert one[1] / one[0] == pytest.approx(14.3e6)


# --------------------------------------------------------------------------- direction of effects
@pytest.fixture(scope="module")
def half_day_reference():
    sim = KilnSim(dt_s=COARSE_DT)
    run(sim, 12)
    return sim


def mean_solid(sim: KilnSim) -> float:
    return sum(sim.solids.brick_c) / len(sim.solids.brick_c)


def test_no_fuel_means_the_kiln_cools(half_day_reference):
    cold = KilnSim(dt_s=COARSE_DT, fuel_on=False)
    start = mean_solid(cold)
    records = run(cold, 12)
    assert sum(r["fuel_fed_kg"] for r in records) == 0.0
    assert mean_solid(cold) < start
    assert max(cold.point_c) < max(half_day_reference.point_c) - 50.0      # the brick holds a lot of heat


def test_wetter_wood_without_adjustment_runs_cooler(half_day_reference):
    no_adjust = dataclasses.replace(KilnParams(), moisture_compensation=0.0)
    wet = KilnSim(kp=no_adjust, dt_s=COARSE_DT, fuel_moisture=0.40)
    run(wet, 12)
    assert mean_solid(wet) < mean_solid(half_day_reference)
    assert max(wet.point_c) < max(half_day_reference.point_c)


def test_wetter_wood_with_the_plan_adjustment_is_fed_heavier(half_day_reference):
    wet = KilnSim(dt_s=COARSE_DT, fuel_moisture=0.35)
    run(wet, 12)
    assert wet.fuel_fed_total_kg > 1.1 * half_day_reference.fuel_fed_total_kg
    assert abs(mean_solid(wet) - mean_solid(half_day_reference)) < 10.0          # same heat, a little more vapour


def test_bigger_charges_run_hotter(half_day_reference):
    heavy = KilnSim(dt_s=COARSE_DT, charge_size_factor=1.3)
    run(heavy, 12)
    assert mean_solid(heavy) > mean_solid(half_day_reference)
    assert max(heavy.point_c) > max(half_day_reference.point_c)


# --------------------------------------------------------------------------- numerics
def test_300_s_step_matches_60_s_step():
    fine, coarse = KilnSim(dt_s=60.0), KilnSim(dt_s=COARSE_DT)
    fine_records, coarse_records = run(fine, 6), run(coarse, 6)
    assert max(abs(a - b) for a, b in zip(fine.point_c, coarse.point_c)) < 15.0
    assert max(abs(a - b) for a, b in zip(fine.solids.tile_c, coarse.solids.tile_c)) < 15.0
    mean = lambda records, key: sum(r[key] for r in records[-len(records) // 3:]) / (len(records) // 3)
    assert mean(fine_records, "t_exhaust_c") == pytest.approx(mean(coarse_records, "t_exhaust_c"), abs=5.0)
    assert sum(fine.solids.water_kg) == pytest.approx(sum(coarse.solids.water_kg), rel=0.02)


def test_implicit_update_does_not_overshoot_at_a_huge_step():
    kp = KilnParams()
    flows = GasFlows(along_kg_s=(3.0, 0.0), inlet_kg_s=(3.0, 0.0), damper_kg_s=(0.0, 3.0))
    solids = Solids(tile_c=[900.0, 900.0], brick_c=[900.0, 900.0], water_kg=[0.0, 0.0], has_tiles=[True, False])
    r = thermal_step(kp, flows, solids, [0.0, 0.0], [0.0, 0.0], t_amb_c=30.0, t_ref_c=30.0, dt_s=1e7)
    for t in solids.tile_c[:1] + solids.brick_c:
        assert 30.0 <= t <= 900.0
    assert all(30.0 <= t <= 900.0 for t in r.gas_c)


def test_gas_never_leaves_hotter_than_it_came_or_colder_than_the_walls():
    kp = KilnParams()
    flows = GasFlows(along_kg_s=(2.0, 0.0), inlet_kg_s=(2.0, 0.0), damper_kg_s=(0.0, 2.0))
    solids = Solids(tile_c=[300.0, 200.0], brick_c=[300.0, 200.0], water_kg=[0.0, 0.0], has_tiles=[True, True])
    r = thermal_step(kp, flows, solids, [0.0, 0.0], [0.0, 0.0], t_amb_c=30.0, t_ref_c=30.0, dt_s=60.0)
    assert 30.0 < r.gas_c[0] < 300.0                 # ambient air warmed by the first unit, not past its walls
    assert r.gas_c[0] > r.gas_c[1] > 30.0 or r.gas_c[1] >= 200.0 - 1e-6


def test_flow_order_follows_the_gas_and_rejects_a_closed_loop():
    order = flow_order((1.0, 1.0, 0.0, -1.0))         # 0 -> 1 -> 2 <- 3
    assert order.index(0) < order.index(1) < order.index(2) and order.index(3) < order.index(2)
    with pytest.raises(ValueError):
        flow_order((1.0, 1.0, 1.0))


# --------------------------------------------------------------------------- upsets and controls
def test_skip_upset_stops_charges_on_the_firing_zone():
    sim = KilnSim(dt_s=COARSE_DT)
    firing = sim.skip_charges(2)
    assert len(firing) >= 15
    fed = sum(r["fuel_fed_kg"] for r in run(sim, 0.5))
    reference = KilnSim(dt_s=COARSE_DT)
    assert fed < 0.5 * sum(r["fuel_fed_kg"] for r in run(reference, 0.5))
    assert "upset" in sim.last_reason


def test_damper_and_door_overrides_reach_the_flow_network():
    sim = KilnSim(dt_s=COARSE_DT)
    closed = next(u for u in sim.kiln_state().units if u.firebox.has_damper and u.damper_lift_in == 0.0
                  and u.zone == ZONE_PREHEATING)
    sim.override_damper(closed.firebox.number, 9.0)
    sim.step()
    assert sim.snapshot()["units"][closed.firebox.number - 1]["damper_share"] > 0.05
    door = next(u for u in sim.kiln_state().units if u.firebox.has_door and u.door == "closed")
    sim.override_door(door.firebox.number, "open")
    assert sim.kiln_state().unit(door.firebox.number).door == "open"
    sim.clear_upsets()
    assert not sim.damper_overrides and not sim.door_overrides


def test_travel_rate_change_keeps_the_fire_where_it_is():
    sim = KilnSim(dt_s=COARSE_DT)
    run(sim, 5)
    before = sim.kiln_state().lead
    sim.set_travel_rate(12.0)
    assert sim.kiln_state().lead == pytest.approx(before)
    run(sim, 2)
    assert (sim.kiln_state().lead - before) % 60 == pytest.approx(1.0, abs=0.01)     # 12/day = 1 per 2 h


@pytest.mark.parametrize("make", [
    lambda: KilnSim(dt_s=0.0),
    lambda: KilnSim(dt_s=1000.0),
    lambda: KilnSim(rpm=-5.0),
    lambda: KilnSim(fuel_moisture=0.9),
    lambda: KilnSim(charge_size_factor=-1.0),
    lambda: KilnSim(start_lead=0.0),
    lambda: KilnSim(t_amb_c=80.0),
    lambda: KilnParams(brick_kg=-1.0),
    lambda: KilnParams(ramp_share=0.8, taper_share=0.5),
    lambda: charge_plan(KilnParams(), 0),
    lambda: lhv_j_kg(KilnParams(), 1.5),
    lambda: KilnSim().override_damper(2, 5.0),          # firebox 2 is a mid unit: no damper
    lambda: KilnSim().override_damper(3, 40.0),         # beyond the 23.5 in maximum lift
    lambda: KilnSim().override_door(1, "open"),         # firebox 1 is a half room: no door
    lambda: KilnSim().override_door(3, "ajar"),
    lambda: KilnSim().override_door(3.0, "open"),
    lambda: KilnSim().skip_charges(-1),
    lambda: KilnSim().set_travel_rate(0.0),
    lambda: Schedule(ru_per_day=-1),
])
def test_invalid_inputs_raise_value_error(make):
    with pytest.raises(ValueError):
        make()
