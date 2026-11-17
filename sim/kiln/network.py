"""
Gas flow through the kiln ring.

    open doors -> cooling zone -> firing zone -> pre-heating -> lifted dampers -> main flue -> fan

The paper seal cuts the ring, so the tunnel is a chain of 60 units: it starts in the handling zone
just beyond the seal and ends at the sealed unit. Each unit is a node with a pressure. Three kinds
of opening carry gas:

  * along the tunnel, from one unit to the next (resistance of the tile setting);
  * in from the room: open or part-open doors, leaks, portholes open for a fuel charge;
  * out to the main flue: lifted dampers.

Every opening obeys ``mass flow = area * sqrt(2 * density * pressure difference)``. The node
pressures are found by repeatedly linearising that law and solving the chain (a tridiagonal
system), which is the usual way to solve a pipe network.

Because every opening follows the same square-root law, all flows scale together with the square
root of the main-flue suction. The whole kiln therefore looks to the fan like ONE opening whose
size does not depend on the suction: ``equivalent_area_m2``. That is what joins this model to the
stage 1 fan and chimney model (``couple_to_exhaust``).

Simplifications: buoyancy inside the kiln and the pressure loss along the main flue are ignored;
every unit in the handling zone is treated as empty.
"""
import math
from dataclasses import dataclass

from sim.gas import density, AIR_MOLAR_MASS_G_MOL
from sim.kiln.layout import FIREBOX_COUNT
from sim.kiln.params import KilnParams, INCH_M
from sim.kiln.schedule import (KilnState, UnitState, ZONE_HANDLING, ZONE_PREDRYING, ZONE_DAMPER, ZONE_PREHEATING,
                               ZONE_FIRING, ZONE_COOLING, DOOR_OPEN, DOOR_PART)
from sim.plant import solve_steady, OperatingPoint

REFERENCE_SUCTION_PA = 100.0       # the network is solved at this main-flue suction; flows scale from it
MAX_ITERATIONS = 200
CONVERGENCE_REL = 1e-9
MIN_DP_PA = 1e-9                   # keeps the linearised conductance finite at zero pressure difference
P_ATM_PA = 101325.0


def damper_area_m2(kp: KilnParams, lift_in: float) -> float:
    """
    Open area of a cone-in-ring damper. At small lift the gap between cone and ring (a "curtain"
    round the ring) limits the flow; at large lift the ring bore does. The two act in series.
    """
    if lift_in <= 0.0:
        return 0.0
    curtain = math.pi * kp.damper_bore_m * lift_in * INCH_M * kp.damper_curtain_factor
    bore = math.pi / 4.0 * kp.damper_bore_m ** 2
    return 1.0 / math.sqrt(1.0 / curtain ** 2 + 1.0 / bore ** 2)


def nominal_temperatures(state: KilnState, t_amb_c: float, peak_c: float = 900.0,
                         exhaust_c: float = 130.0) -> list[float]:
    """
    A plausible gas temperature for every unit from its zone alone. Used until the heat model
    (build stage H) supplies real ones: hot in the firing zone, cooling off behind it, falling
    through the pre-heating zone to the exhaust temperature at the dampers.
    """
    temps = []
    firing = [u for u in state.units if u.zone == ZONE_FIRING]
    cooling = [u for u in state.units if u.zone == ZONE_COOLING]
    preheat = [u for u in state.units if u.zone == ZONE_PREHEATING]
    oldest = min((u.ahead_ru for u in firing), default=0.0)
    coolest = min((u.ahead_ru for u in cooling), default=oldest)
    furthest = max((u.ahead_ru for u in preheat), default=1.0)
    for u in state.units:
        if u.zone == ZONE_FIRING:
            temps.append(peak_c - 200.0 * max(0.0, 1.0 + u.ahead_ru / 5.0))     # last five units still warming up
        elif u.zone == ZONE_COOLING:
            fraction = (u.ahead_ru - coolest) / max(oldest - coolest, 1e-9)       # 0 at the open doors, 1 at the fire
            temps.append(t_amb_c + 30.0 + (peak_c - 100.0 - t_amb_c - 30.0) * fraction)
        elif u.zone == ZONE_PREHEATING:
            fraction = u.ahead_ru / max(furthest, 1e-9)
            temps.append(peak_c - 200.0 + (exhaust_c + 20.0 - (peak_c - 200.0)) * fraction)
        elif u.zone == ZONE_DAMPER:
            temps.append(exhaust_c)
        elif u.zone == ZONE_PREDRYING:
            temps.append(t_amb_c + 10.0)
        else:
            temps.append(t_amb_c + 5.0)
    return temps


@dataclass(frozen=True)
class NetworkSolution:
    """Flows at the reference suction. Lists are indexed by firebox number - 1."""
    suction_pa: float
    pressure_pa: tuple[float, ...]         # gauge pressure in each unit (negative = suction)
    along_kg_s: tuple[float, ...]          # flow from unit n to unit n+1 (clockwise positive)
    inlet_kg_s: tuple[float, ...]          # air entering unit n from the room
    damper_kg_s: tuple[float, ...]         # gas leaving unit n through its damper
    total_kg_s: float                      # sum of the damper flows = what the fan receives
    t_exhaust_c: float                     # mixed temperature of the gas reaching the main flue
    equivalent_area_m2: float              # the whole kiln as one opening, as the fan sees it
    iterations: int

    def scaled(self, suction_pa: float) -> "NetworkSolution":
        """The same solution at another main-flue suction: every flow scales with its square root."""
        k = math.sqrt(max(suction_pa, 0.0) / self.suction_pa)
        return NetworkSolution(
            suction_pa=suction_pa, pressure_pa=tuple(p * k * k for p in self.pressure_pa),
            along_kg_s=tuple(m * k for m in self.along_kg_s), inlet_kg_s=tuple(m * k for m in self.inlet_kg_s),
            damper_kg_s=tuple(m * k for m in self.damper_kg_s), total_kg_s=self.total_kg_s * k,
            t_exhaust_c=self.t_exhaust_c, equivalent_area_m2=self.equivalent_area_m2, iterations=self.iterations)


def _unit_areas(kp: KilnParams, unit: UnitState, charging: bool) -> tuple[float, float, float]:
    """(area along the tunnel to the next unit, area in from the room, area out through the damper)."""
    if unit.paper_sealed:
        along = 0.0                                      # the paper seal closes the tunnel beyond this unit
    elif not unit.firebox.has_platform:
        along = kp.flue_free_area_m2
    elif unit.zone == ZONE_HANDLING:
        along = kp.empty_free_area_m2
    else:
        along = kp.setting_free_area_m2
    if unit.door == DOOR_OPEN:
        inlet = kp.door_open_area_m2
    elif unit.door == DOOR_PART:
        inlet = kp.door_part_area_m2
    else:
        inlet = kp.leak_area_m2
    if charging and unit.zone == ZONE_FIRING:
        inlet += kp.porthole_area_m2
    return along, inlet, damper_area_m2(kp, unit.damper_lift_in)


def _solve_chain(lower: list[float], diag: list[float], upper: list[float], rhs: list[float]) -> list[float]:
    """Thomas algorithm for a tridiagonal system."""
    n = len(diag)
    c, d = [0.0] * n, [0.0] * n
    c[0] = upper[0] / diag[0]
    d[0] = rhs[0] / diag[0]
    for i in range(1, n):
        denominator = diag[i] - lower[i] * c[i - 1]
        c[i] = upper[i] / denominator
        d[i] = (rhs[i] - lower[i] * d[i - 1]) / denominator
    x = [0.0] * n
    x[-1] = d[-1]
    for i in range(n - 2, -1, -1):
        x[i] = d[i] - c[i] * x[i + 1]
    return x


def solve_network(state: KilnState, kp: KilnParams, temps_c: list[float], t_amb_c: float,
                  charging_units: frozenset[int] = frozenset(),
                  gas_molar_mass_g_mol: float = 28.5) -> NetworkSolution:
    """
    Flows and pressures in the ring for a kiln state and a gas temperature per unit.

    ``charging_units`` are firebox numbers whose portholes are open at this moment.
    """
    n = FIREBOX_COUNT
    sealed = [u.firebox.number for u in state.units if u.paper_sealed]
    # Chain order: start just beyond the paper seal and go clockwise, so the sealed unit is last.
    start = sealed[0] % n if sealed else 0
    order = [(start + i) % n for i in range(n)]             # indices into state.units

    areas = [_unit_areas(kp, state.units[i], state.units[i].firebox.number in charging_units) for i in order]
    rho_unit = [density(P_ATM_PA, temps_c[i], gas_molar_mass_g_mol) for i in order]
    rho_amb = density(P_ATM_PA, t_amb_c, AIR_MOLAR_MASS_G_MOL)
    p_flue = -REFERENCE_SUCTION_PA

    # coefficient c in  m = c * sqrt(|dP|)  for each opening
    c_along = [a * math.sqrt(2.0 * rho) for (a, _, _), rho in zip(areas, rho_unit)]
    c_along[-1] = 0.0                                        # the chain is not closed into a ring
    c_inlet = [a * math.sqrt(2.0 * rho_amb) for _, a, _ in areas]
    c_damper = [a * math.sqrt(2.0 * rho) for (_, _, a), rho in zip(areas, rho_unit)]

    pressure = [p_flue / 2.0] * n
    iterations = 0
    for iterations in range(1, MAX_ITERATIONS + 1):
        g_along = [c / math.sqrt(max(abs(pressure[i] - pressure[i + 1]), MIN_DP_PA)) if i < n - 1 else 0.0
                   for i, c in enumerate(c_along)]
        g_inlet = [c / math.sqrt(max(abs(pressure[i]), MIN_DP_PA)) for i, c in enumerate(c_inlet)]
        g_damper = [c / math.sqrt(max(abs(pressure[i] - p_flue), MIN_DP_PA)) for i, c in enumerate(c_damper)]
        lower = [0.0] + [-g for g in g_along[:-1]]
        upper = [-g for g in g_along[:-1]] + [0.0]
        diag = [g_inlet[i] + g_damper[i] + g_along[i] + (g_along[i - 1] if i else 0.0) for i in range(n)]
        rhs = [g_damper[i] * p_flue for i in range(n)]
        solved = _solve_chain(lower, diag, upper, rhs)
        change = max(abs(a - b) for a, b in zip(solved, pressure))
        pressure = [0.5 * (a + b) for a, b in zip(solved, pressure)]     # damping
        if change < CONVERGENCE_REL * REFERENCE_SUCTION_PA:
            break

    def flow(c: float, dp: float) -> float:
        return math.copysign(c * math.sqrt(abs(dp)), dp)

    along = [flow(c_along[i], pressure[i] - pressure[i + 1]) if i < n - 1 else 0.0 for i in range(n)]
    inlet = [flow(c_inlet[i], 0.0 - pressure[i]) for i in range(n)]
    damper = [flow(c_damper[i], pressure[i] - p_flue) for i in range(n)]
    total = sum(damper)
    t_exhaust = (sum(m * temps_c[i] for m, i in zip(damper, order)) / total) if total > 0.0 else t_amb_c
    rho_exhaust = density(P_ATM_PA, t_exhaust, gas_molar_mass_g_mol)
    equivalent = total / math.sqrt(2.0 * rho_exhaust * REFERENCE_SUCTION_PA)

    def by_firebox(values: list[float]) -> tuple[float, ...]:
        out = [0.0] * n
        for value, i in zip(values, order):
            out[i] = value
        return tuple(out)

    return NetworkSolution(suction_pa=REFERENCE_SUCTION_PA, pressure_pa=by_firebox(pressure),
                           along_kg_s=by_firebox(along), inlet_kg_s=by_firebox(inlet),
                           damper_kg_s=by_firebox(damper), total_kg_s=total, t_exhaust_c=t_exhaust,
                           equivalent_area_m2=equivalent, iterations=iterations)


def couple_to_exhaust(exhaust_params, network: NetworkSolution, rpm: float, t_amb_c: float,
                      guess: float | None = None) -> tuple[OperatingPoint, NetworkSolution]:
    """
    Join the kiln to the stage 1 fan, plate and chimney model.

    The kiln's equivalent opening and mixed exhaust temperature replace stage 1's fixed
    ``kiln_free_area_m2`` and ``t_gas_c``. Stage 1 then gives the flow and the suction at the fan
    inlet, and the kiln flows are scaled to that suction.
    """
    factor = network.equivalent_area_m2 / exhaust_params.kiln_free_area_m2
    op = solve_steady(exhaust_params, rpm, network.t_exhaust_c, t_amb_c, guess=guess, kiln_area_factor=factor)
    suction = max(0.0, exhaust_params.kiln_gauge_pa - op.p_fan_in_pa)
    return op, network.scaled(suction)
