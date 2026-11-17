"""
The whole kiln in time: schedule, fuel, gas flow, heat, and the stage 1 fan and chimney.

One call to ``KilnSim.step()`` advances the kiln by ``dt_s`` (60 s by default; 300 s is fine too):

  1. ``kiln_state`` says where the fire is: zones, damper lifts, doors, charge numbers. Operator
     upsets (a damper left open, a door opened early) are laid over it.
  2. Charges fall due on the firing units (one every 15 minutes each) and are weighed by the
     firing plan rules (``sim.kiln.fuel``). Units being charged have their portholes open.
  3. ``solve_network`` gives the flows for the current gas temperatures; ``couple_to_exhaust``
     joins them to the stage 1 fan, plate and chimney at the set fan speed. The scaled flows are used.
  4. Fuel on each grate burns; ``thermal_step`` follows the gas round the ring and updates the
     tiles, brick and tile water (``sim.kiln.thermal``).
  5. Tiles are replaced in the handling zone (rule below), point readings follow the gas, and an
     energy and mass account is kept.

Tile replacement rule: a room unit's tiles are marked "fired" once the unit has been in the firing
zone. When a fired unit is ``reload_delay_ru`` room units into the handling zone (counted from the
point where its door opens fully) the fired tiles are taken out, carrying their heat with them,
and green tiles at ambient temperature with their full water load are put in. The brick keeps its
heat. In the plant unloading, cleaning and loading take many hours; doing it at one instant is a
simplification.

The gas leaving the kiln comes from the thermal march (it includes fuel and vapour mass). The fan
operating point (P1, P2, flow at the plate) is solved from the network's air flows and the mixed
exhaust temperature of the previous step, so it lags the kiln by one step and leaves out the few
per cent of extra mass from fuel and vapour.

All heat-transfer and brick numbers are TUNED PLACEHOLDERS (see ``sim.kiln.params``), not site data.
"""
import dataclasses
import math
from collections import deque

from sim.kiln.fuel import burn, charge_mass_kg, charge_plan, lhv_j_kg, MAX_MOISTURE
from sim.kiln.layout import FIREBOX_COUNT, LAYOUT
from sim.kiln.network import couple_to_exhaust, nominal_temperatures, solve_network
from sim.kiln.params import KilnParams
from sim.kiln.schedule import (Schedule, KilnState, kiln_state, ZONE_FIRING, ZONE_HANDLING, DOOR_OPEN,
                               DOOR_PART, DOOR_CLOSED)
from sim.kiln.thermal import GasFlows, Solids, thermal_step, stored_heat_j
from sim.params import make_params

SECONDS_PER_HOUR = 3600.0
DEFAULT_DT_S = 60.0
MAX_DT_S = 900.0                   # one charge interval: at most one charge per unit per step
DEFAULT_RPM = 380.0
MAX_RPM = 1500.0
DEFAULT_T_AMB_C = 30.0
MAX_DAMPER_LIFT_IN = 23.5          # Kiln-Domain: maximum damper lift
DOORS = (DOOR_CLOSED, DOOR_PART, DOOR_OPEN)
ENERGY_TERMS = ("fuel", "air_in", "tiles_in", "exhaust", "vented", "wall", "latent", "tiles_out")


class KilnSim:
    """Whole-kiln simulation driver. Not thread-safe on its own; the server wraps it in a lock."""

    def __init__(self, kp: KilnParams | None = None, schedule: Schedule | None = None, exhaust_params=None,
                 dt_s: float = DEFAULT_DT_S, rpm: float = DEFAULT_RPM, t_amb_c: float = DEFAULT_T_AMB_C,
                 fuel_moisture: float | None = None, charge_size_factor: float = 1.0, start_lead: float = 1.0,
                 fuel_on: bool = True):
        self.kp = kp or KilnParams()
        self.schedule = schedule or Schedule()
        self.exhaust = exhaust_params if exhaust_params is not None else make_params()
        if not 0.0 < dt_s <= MAX_DT_S or dt_s > self.schedule.charge_interval_h * SECONDS_PER_HOUR:
            raise ValueError(f"time step must be above 0 and at most one charge interval ({MAX_DT_S:.0f} s)")
        if not 1.0 <= start_lead < FIREBOX_COUNT + 1:
            raise ValueError("start lead must be a firebox position, 1 <= lead < 61")
        self.dt_s = float(dt_s)
        self.time_s = 0.0
        self.fuel_on = fuel_on
        self.set_rpm(rpm)
        self.set_ambient(t_amb_c)
        self.set_moisture(self.kp.fuel_moisture_ref if fuel_moisture is None else fuel_moisture)
        self.set_charge_factor(charge_size_factor)
        self.t_ref_c = self.t_amb_c                      # enthalpy reference for the energy account
        self._origin_h, self._origin_lead = 0.0, float(start_lead)
        self._plan = charge_plan(self.kp, self.schedule.charge_count)
        self.damper_overrides: dict[int, float] = {}
        self.door_overrides: dict[int, str] = {}
        self._op_guess: float | None = None

        state = self.kiln_state()
        start = nominal_temperatures(state, self.t_amb_c)
        n = FIREBOX_COUNT
        has_tiles = [u.firebox.has_platform for u in state.units]
        self.fresh = [has_tiles[i] and (u.ahead_ru > 0.0 or self._past_reload_point(u)) for i, u in enumerate(state.units)]
        water = [self.kp.tile_water_kg if self.fresh[i] and start[i] < self.kp.boiling_c else 0.0 for i in range(n)]
        self.solids = Solids(tile_c=list(start), brick_c=list(start), water_kg=water, has_tiles=has_tiles)
        self.gas_c = list(start)
        self.point_c = list(start)
        self.grate_kg = [0.0] * n
        self.grate_j = [0.0] * n
        self.last_charge = [u.charge_number or 0 for u in state.units]   # charges already given before t = 0
        self.skip_left = [0] * n
        self.last_reason = [""] * n
        self._fuel_left_from_before_start(state)
        self.energy = {term: 0.0 for term in ENERGY_TERMS}
        self._stored_start = stored_heat_j(self.kp, self.solids, self.t_ref_c)
        self.fuel_fed_total_kg = 0.0
        self._fed_recent: deque[tuple[float, float]] = deque()    # (time, kg) of the last hour's charges
        self.last_state = state
        self.last_result = None
        self.last_op = None
        self.last_network = None
        self.last_charging: frozenset[int] = frozenset()

    # ------------------------------------------------------------------ controls (validated)
    def set_rpm(self, rpm: float) -> None:
        if not 0.0 <= rpm <= MAX_RPM:
            raise ValueError(f"fan speed must be 0..{MAX_RPM:.0f} rpm")
        self.rpm = float(rpm)

    def set_ambient(self, t_amb_c: float) -> None:
        if not -20.0 <= t_amb_c <= 50.0:
            raise ValueError("ambient temperature must be -20..50 degC")
        self.t_amb_c = float(t_amb_c)

    def set_moisture(self, moisture: float) -> None:
        if not 0.0 <= moisture <= MAX_MOISTURE:
            raise ValueError(f"fuel moisture must be 0..{MAX_MOISTURE} (fraction, wet basis)")
        self.fuel_moisture = float(moisture)

    def set_charge_factor(self, factor: float) -> None:
        if not 0.0 <= factor <= 3.0:
            raise ValueError("charge size factor must be 0..3")
        self.charge_size_factor = float(factor)

    def set_travel_rate(self, ru_per_day: float) -> None:
        """Change the fire travel rate from now on. The fire continues from where it is."""
        new = dataclasses.replace(self.schedule, ru_per_day=float(ru_per_day))   # validates
        self._origin_lead = self.kiln_state().lead
        self._origin_h = self.time_s / SECONDS_PER_HOUR
        self.schedule = new

    def skip_charges(self, count: int) -> list[int]:
        """Upset: skip the next ``count`` charges on every unit firing now. Returns those units."""
        if not 0 <= count <= self.schedule.charge_count:
            raise ValueError(f"skip count must be 0..{self.schedule.charge_count}")
        firing = [u.firebox.number for u in self.kiln_state().units if u.zone == ZONE_FIRING]
        for number in firing:
            self.skip_left[number - 1] = count
        return firing

    @staticmethod
    def _box(number: int):
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= FIREBOX_COUNT:
            raise ValueError(f"firebox number must be a whole number 1..{FIREBOX_COUNT}")
        return LAYOUT[number - 1]

    def override_damper(self, number: int, lift_in: float | None) -> None:
        """Upset: hold a damper at ``lift_in`` inches whatever the schedule says (None clears it)."""
        box = self._box(number)
        if not box.has_damper:
            raise ValueError(f"firebox {number} has no damper")
        if lift_in is None:
            self.damper_overrides.pop(number, None)
            return
        if not 0.0 <= lift_in <= MAX_DAMPER_LIFT_IN:
            raise ValueError(f"damper lift must be 0..{MAX_DAMPER_LIFT_IN} in")
        self.damper_overrides[number] = float(lift_in)

    def override_door(self, number: int, door: str | None) -> None:
        """Upset: hold a door in a position ("closed", "part-open", "open"); None clears it."""
        box = self._box(number)
        if not box.has_door:
            raise ValueError(f"firebox {number} has no door")
        if door is None:
            self.door_overrides.pop(number, None)
            return
        if door not in DOORS:
            raise ValueError(f"door must be one of {DOORS}")
        self.door_overrides[number] = door

    def clear_upsets(self) -> None:
        self.damper_overrides.clear()
        self.door_overrides.clear()
        self.skip_left = [0] * FIREBOX_COUNT

    # ------------------------------------------------------------------ helpers
    def kiln_state(self) -> KilnState:
        """Schedule state now, with any operator upsets laid over it."""
        hours = self.time_s / SECONDS_PER_HOUR - self._origin_h
        state = kiln_state(self.schedule, hours, start_lead=self._origin_lead)
        if not self.damper_overrides and not self.door_overrides:
            return state
        units = list(state.units)
        for number, lift in self.damper_overrides.items():
            units[number - 1] = dataclasses.replace(units[number - 1], damper_lift_in=lift)
        for number, door in self.door_overrides.items():
            units[number - 1] = dataclasses.replace(units[number - 1], door=door)
        return dataclasses.replace(state, units=tuple(units))

    def _fuel_left_from_before_start(self, state: KilnState) -> None:
        """
        A run starts in the middle of firing, so each firing unit already has its latest charge
        burning: put what is left of it on the grate (the charge burns exponentially since it was fed).
        """
        if not self.fuel_on:
            return
        lhv = lhv_j_kg(self.kp, self.fuel_moisture)
        interval_s = self.schedule.charge_interval_h * SECONDS_PER_HOUR
        for i, u in enumerate(state.units):
            if u.charge_number is None:
                continue
            kg, reason = charge_mass_kg(self.kp, self._plan, u.charge_number, self.point_c[i],
                                        self.fuel_moisture, self.charge_size_factor)
            since_s = u.firing_hours * SECONDS_PER_HOUR - (u.charge_number - 1) * interval_s
            left = kg * math.exp(-max(0.0, since_s) / self.kp.burn_tau_s)
            self.grate_kg[i], self.grate_j[i], self.last_reason[i] = left, left * lhv, reason

    def _past_reload_point(self, unit) -> bool:
        behind_tail = -unit.ahead_ru - self.schedule.firing_zone_ru
        return unit.zone == ZONE_HANDLING and behind_tail >= self.schedule.full_open_gap_ru + self.kp.reload_delay_ru

    def _reload_tiles(self, state: KilnState) -> None:
        kp, c_t = self.kp, self.kp.tile_dry_kg * self.kp.tile_cp_j_kg_k
        for i, u in enumerate(state.units):
            if not self.solids.has_tiles[i]:
                continue
            if u.zone == ZONE_FIRING:
                self.fresh[i] = False
            elif not self.fresh[i] and self._past_reload_point(u):
                self.energy["tiles_out"] += c_t * (self.solids.tile_c[i] - self.t_ref_c)
                self.energy["tiles_in"] += c_t * (self.t_amb_c - self.t_ref_c)
                self.solids.tile_c[i] = self.t_amb_c
                self.solids.water_kg[i] = kp.tile_water_kg
                self.fresh[i] = True

    def _feed(self, state: KilnState) -> tuple[float, set[int]]:
        """Put due charges on the grates. Returns (kg fed this step, units being charged)."""
        fed, charging = 0.0, set()
        lhv = lhv_j_kg(self.kp, self.fuel_moisture)
        for i, u in enumerate(state.units):
            if u.charge_number is None:
                self.last_charge[i] = 0
                continue
            if u.charge_number <= self.last_charge[i]:
                continue
            self.last_charge[i] = u.charge_number
            if not self.fuel_on:
                continue
            if self.skip_left[i] > 0:
                self.skip_left[i] -= 1
                self.last_reason[i] = "upset"
                continue
            kg, reason = charge_mass_kg(self.kp, self._plan, u.charge_number, self.point_c[i],
                                        self.fuel_moisture, self.charge_size_factor)
            self.last_reason[i] = reason
            if kg > 0.0:
                self.grate_kg[i] += kg
                self.grate_j[i] += kg * lhv
                fed += kg
                charging.add(u.firebox.number)
        return fed, charging

    # ------------------------------------------------------------------ stepping
    def step(self) -> dict:
        dt, kp = self.dt_s, self.kp
        state = self.kiln_state()
        self._reload_tiles(state)
        fed, charging = self._feed(state)
        # Portholes are open for ``porthole_open_s`` per charge. A step longer than that sees them with
        # their time-averaged area (open time / step), so the extra air does not depend on the step.
        self.last_charging = frozenset(charging)
        open_fraction = min(1.0, kp.porthole_open_s / dt)
        net_kp = kp if open_fraction == 1.0 else dataclasses.replace(kp, porthole_area_m2=kp.porthole_area_m2 * open_fraction)

        network = solve_network(state, net_kp, self.gas_c, self.t_amb_c, charging_units=self.last_charging)
        op, scaled = couple_to_exhaust(self.exhaust, network, self.rpm, self.t_amb_c, guess=self._op_guess)
        self._op_guess = op.mass_flow_kg_s

        fuel_w, fuel_kg_s = [0.0] * FIREBOX_COUNT, [0.0] * FIREBOX_COUNT
        for i in range(FIREBOX_COUNT):
            if self.grate_kg[i] > 0.0:
                burnt, released, self.grate_kg[i], self.grate_j[i] = burn(self.grate_kg[i], self.grate_j[i], dt, kp.burn_tau_s)
                fuel_kg_s[i], fuel_w[i] = burnt / dt, released / dt

        flows = GasFlows(scaled.along_kg_s, scaled.inlet_kg_s, scaled.damper_kg_s)
        result = thermal_step(kp, flows, self.solids, fuel_w, fuel_kg_s, self.t_amb_c, self.t_ref_c, dt)
        lag = 1.0 - math.exp(-dt / kp.thermocouple_tau_s)
        self.point_c = [p + (g - p) * lag for p, g in zip(self.point_c, result.gas_c)]
        self.gas_c = list(result.gas_c)
        self.time_s += dt
        self.fuel_fed_total_kg += fed
        self._fed_recent.append((self.time_s, fed))
        while self._fed_recent[0][0] <= self.time_s - SECONDS_PER_HOUR:
            self._fed_recent.popleft()

        e = self.energy
        e["fuel"] += result.fuel_w * dt
        e["air_in"] += result.air_in_w * dt
        e["exhaust"] += result.exhaust_w * dt
        e["vented"] += result.vented_w * dt
        e["wall"] += result.wall_loss_w * dt
        e["latent"] += result.latent_w * dt
        self.last_state, self.last_result, self.last_op, self.last_network = state, result, op, scaled
        return self._record(state, result, op, fed)

    def energy_balance(self) -> dict:
        """Cumulative energy account since t = 0 (J). ``error`` is what does not add up."""
        e = dict(self.energy)
        e["stored_change"] = stored_heat_j(self.kp, self.solids, self.t_ref_c) - self._stored_start
        e["on_grate"] = sum(self.grate_j)                 # fed but not yet burnt (not in "fuel")
        heat_in = e["fuel"] + e["air_in"] + e["tiles_in"]
        heat_out = e["exhaust"] + e["vented"] + e["wall"] + e["latent"] + e["tiles_out"] + e["stored_change"]
        e["error"] = heat_in - heat_out
        e["relative_error"] = e["error"] / heat_in if heat_in > 0.0 else 0.0
        return e

    def _record(self, state: KilnState, r, op, fed_kg: float) -> dict:
        peak = max(range(FIREBOX_COUNT), key=lambda i: self.point_c[i])
        balance = self.energy_balance()
        return {
            "time_s": self.time_s, "time_h": self.time_s / SECONDS_PER_HOUR, "lead": state.lead,
            "t_exhaust_c": r.exhaust_c, "exhaust_kg_s": r.exhaust_kg_s, "q_plate_m3_s": op.q_m3_s,
            "rpm": self.rpm, "p1_pa": op.p1_pa, "p2_pa": op.p2_pa, "p_fan_in_pa": op.p_fan_in_pa,
            "t_ambient_c": self.t_amb_c,
            "peak_point_c": self.point_c[peak], "peak_unit": peak + 1, "peak_gas_c": max(r.gas_c),
            "peak_tile_c": max(t for t, has in zip(self.solids.tile_c, self.solids.has_tiles) if has),
            "fuel_fed_kg": fed_kg, "fuel_last_hour_kg": sum(kg for _, kg in self._fed_recent),
            "fuel_burnt_kg_s": r.fuel_kg_s, "heat_release_kw": r.fuel_w / 1000.0,
            "air_in_kg_s": r.air_in_kg_s, "vapour_kg_s": r.vapour_kg_s, "vented_kg_s": r.vented_kg_s,
            "exhaust_kw": r.exhaust_w / 1000.0, "wall_loss_kw": r.wall_loss_w / 1000.0, "latent_kw": r.latent_w / 1000.0,
            "energy_error_rel": balance["relative_error"],
            "firing_units": sum(1 for u in state.units if u.zone == ZONE_FIRING),
        }

    def snapshot(self) -> dict:
        """Per-unit values for the GUI at the latest instant."""
        state = self.last_state
        r = self.last_result
        net = self.last_network
        total = sum(r.damper_kg_s) if r else 0.0
        units = []
        for i, u in enumerate(state.units):
            units.append({
                "number": u.firebox.number, "unit": u.firebox.unit, "side": u.firebox.side,
                "zone": u.zone, "door": u.door, "damper_lift_in": u.damper_lift_in,
                "has_door": u.firebox.has_door, "has_damper": u.firebox.has_damper,
                "has_platform": u.firebox.has_platform, "paper_sealed": u.paper_sealed,
                "charge_number": u.charge_number, "last_charge_reason": self.last_reason[i] if u.charge_number else "",
                "charging": u.firebox.number in self.last_charging,
                "gas_c": self.gas_c[i], "point_c": self.point_c[i],
                "tile_c": self.solids.tile_c[i] if self.solids.has_tiles[i] else None,
                "brick_c": self.solids.brick_c[i], "water_kg": self.solids.water_kg[i],
                "grate_kg": self.grate_kg[i], "skip_left": self.skip_left[i],
                "damper_share": (r.damper_kg_s[i] / total) if r and total > 0.0 else 0.0,
                "pressure_pa": net.pressure_pa[i] if net else 0.0,
                "damper_override": u.firebox.number in self.damper_overrides,
                "door_override": u.firebox.number in self.door_overrides,
            })
        s = self.schedule
        return {
            "time_s": self.time_s, "lead": state.lead, "units": units,
            "schedule": {"ru_per_day": s.ru_per_day, "hours_per_ru": s.hours_per_ru,
                         "firing_hours": s.firing_hours, "round_days": s.round_days},
            "controls": {"rpm": self.rpm, "t_amb_c": self.t_amb_c, "fuel_moisture": self.fuel_moisture,
                         "charge_size_factor": self.charge_size_factor, "ru_per_day": s.ru_per_day,
                         "dt_s": self.dt_s},
            "upsets": {"damper_overrides": {str(k): v for k, v in self.damper_overrides.items()},
                       "door_overrides": {str(k): v for k, v in self.door_overrides.items()},
                       "skip_left": sum(self.skip_left)},
            "energy": self.energy_balance(),
        }
