"""
Physical model of the kiln exhaust path:

    kiln -> flue -> fan -> short duct -> orifice plate (P1 | P2, T) -> restriction -> chimney -> sky

The orifice plate sits between the fan and the chimney (owner, 2026-11-16), so P1 and P2 are on
the fan's discharge side: they are negative when natural draft dominates and positive when the fan
pushes hard.

How the flow is found
---------------------
Three things push gas along the path:
  * the kiln gauge pressure (usually near zero);
  * natural draft. The chimney is cut into slices; in each one the hot gas inside is lighter than
    the outside air at the same height: ``draft = g * sum((rho_outside - rho_gas) * dz)``;
  * the fan, with a quadratic fan curve scaled by the affinity laws:
    ``dP_fan = (rho/rho_ref) * (dP_shutoff*(N/N_rated)^2 - c_f*Q^2)``.

Everything else resists with ``dP = k * m_dot^2 / rho``. Balancing the pressures gives

    kiln gauge + draft + fan_gain(N) = m_dot^2 * (sum_i k_i/rho_i + fan_slope term)

which is solved for the mass flow ``m_dot``. The chimney gas cools as it rises (more at low flow),
which changes the draft, so the solve is a short damped fixed-point iteration.

The chimney
-----------
Square in section, tapering linearly from ``chimney_bottom_side_m`` to ``chimney_top_side_m``.
Per slice of height ``dz`` and side ``s``:
  * friction        ``dP = f * (dz / s) * rho * v^2 / 2``   (hydraulic diameter of a square = side)
  * wall heat loss  over the wall area ``4 * s * dz``
and one velocity head is lost at the top opening. The outside air pressure falls with height
(barometric formula), so the outside air is slightly thinner at the top than at the ground.

Simplifications (deliberate; the model is for control behaviour, not design):
  * gas is treated as incompressible for the pressure balance (plate dP is far below 1 % of
    atmospheric);
  * pressures are static pressures; the change of velocity head between sections of different
    size is ignored, except for the exit loss at the chimney top;
  * the gas keeps its temperature through the fan (fan heating ignored);
  * a stopped fan is a passive resistance (no windmilling); flow never reverses (it stalls at 0);
  * the plate's true flow uses the standard orifice equation; the controller's own flow estimate is
    separate (see ``instruments.estimate_flow``) and may be deliberately wrong.

P1 and P2 are returned as gauge pressures relative to the room, like the real
gauge-via-differential transmitters.
"""
import math
from dataclasses import dataclass
from functools import lru_cache

from sim.gas import density, barometric_pressure, G, AIR_MOLAR_MASS_G_MOL, FAN_REF_DENSITY

MAX_ITERATIONS = 200
CONVERGENCE_KG_S = 1e-10
RELAXATION = 0.7                   # share of the new estimate taken each iteration (damping)
DEFAULT_GUESS_KG_S = 1.0           # starts on the "warm chimney" branch, not the cold-chimney one
MIN_WARM_START_KG_S = 0.05         # below this a previous flow is not used as the starting guess
MIN_MASS_FLOW_FOR_COOLING = 1e-6   # kg/s, avoids dividing by zero in the chimney heat-loss term
PERMANENT_LOSS_EXPONENT = 1.9      # permanent loss fraction of the plate dP = 1 - beta**1.9 (common approximation)
CHIMNEY_SLICES = 20                # number of slices the chimney is cut into


@dataclass(frozen=True)
class OperatingPoint:
    """Everything the plant can say about one instant. Pressures are gauge (room at ground = 0)."""
    mass_flow_kg_s: float
    q_m3_s: float              # true volumetric flow at the plate (gas conditions at the plate)
    draft_pa: float            # natural draft available from the chimney
    fan_dp_pa: float           # pressure the fan adds (negative if it is a net restriction)
    plate_dp_pa: float         # differential pressure across the plate (P1 - P2)
    p_fan_in_pa: float
    p_fan_out_pa: float
    p1_pa: float
    p2_pa: float
    p_chimney_base_pa: float   # after the plate's pressure recovery and the restriction
    p_top_residual_pa: float   # pressure left over at the chimney top; 0 at steady state
    loss_kiln_pa: float
    loss_fan_to_plate_pa: float
    loss_plate_permanent_pa: float
    loss_restriction_pa: float
    loss_chimney_friction_pa: float
    loss_exit_pa: float
    t_gas_c: float             # gas leaving the kiln = temperature at the fan and at the plate
    t_chimney_mean_c: float
    t_chimney_top_c: float
    rho_plate: float           # gas density at the fan and the plate
    stalled: bool              # True when nothing is pushing gas forward (no flow)


def _circle_area(diameter_m: float) -> float:
    return math.pi / 4.0 * diameter_m ** 2


@dataclass(frozen=True)
class _LossCoefficients:
    """Resistance coefficients, each in dP = k * m_dot^2 / rho form."""
    k_kiln: float            # kiln, dampers and flue up to the fan
    k_fan_to_plate: float
    k_plate_full: float      # full plate dP (what the transmitters see)
    k_plate_loop: float      # permanent loss part (what the fan/draft must overcome)
    k_restriction: float     # unexplained loss between the plate and the chimney
    fan_slope: float         # c_f in the fan curve, Pa / (m3/s)^2


def _loss_coefficients(p) -> _LossCoefficients:
    a_duct = _circle_area(p.duct_diameter_m)
    a_bore = _circle_area(p.plate_beta * p.duct_diameter_m)
    k_plate_full = (1.0 - p.plate_beta ** 4) / (2.0 * p.plate_cd ** 2 * a_bore ** 2)
    permanent_fraction = 1.0 - p.plate_beta ** PERMANENT_LOSS_EXPONENT
    return _LossCoefficients(
        k_kiln=1.0 / (2.0 * p.kiln_free_area_m2 ** 2),
        k_fan_to_plate=p.k_fan_to_plate / (2.0 * a_duct ** 2),
        k_plate_full=k_plate_full,
        k_plate_loop=k_plate_full * permanent_fraction,
        k_restriction=1.0 / (2.0 * p.restriction_free_area_m2 ** 2),
        fan_slope=p.fan_shutoff_dp_pa / p.fan_max_flow_m3s ** 2,
    )


# --------------------------------------------------------------------------- chimney
@lru_cache(maxsize=64)
def chimney_geometry(height_m: float, bottom_side_m: float, top_side_m: float,
                     slices: int = CHIMNEY_SLICES) -> tuple[float, tuple[float, ...], tuple[float, ...]]:
    """Slice height, and the mid-height and inside side length of every slice (base first)."""
    dz = height_m / slices
    z_mid = tuple((i + 0.5) * dz for i in range(slices))
    sides = tuple(bottom_side_m + (top_side_m - bottom_side_m) * z / height_m for z in z_mid)
    return dz, z_mid, sides


@dataclass(frozen=True)
class ChimneyState:
    """The chimney at one instant, slice by slice (index 0 is the lowest slice)."""
    dz: float
    z_mid: tuple[float, ...]
    side: tuple[float, ...]
    t_gas_c: tuple[float, ...]         # mean gas temperature in the slice
    rho_gas: tuple[float, ...]
    rho_outside: tuple[float, ...]     # outside air at the same height
    p_outside_abs: tuple[float, ...]
    draft_pa: float
    k_friction: float                  # wall friction of the whole chimney, dP = k * m_dot^2
    k_exit: float                      # one velocity head at the top opening, dP = k * m_dot^2
    t_mean_c: float
    t_top_c: float
    rho_top: float


def chimney_state(p, mass_flow: float, t_base_c: float, t_amb_c: float,
                  slices: int = CHIMNEY_SLICES) -> ChimneyState:
    """March up the chimney: the gas cools towards ambient, and each slice adds draft and friction."""
    dz, z_mid, sides = chimney_geometry(p.chimney_height_m, p.chimney_bottom_side_m,
                                        p.chimney_top_side_m, slices)
    heat_capacity_rate = max(mass_flow, MIN_MASS_FLOW_FOR_COOLING) * p.gas_cp_j_kg_k
    t_in = t_base_c
    temps, rho_gas, rho_out, p_out = [], [], [], []
    draft = 0.0
    k_friction = 0.0
    for z, side in zip(z_mid, sides):
        cooling = math.exp(-p.chimney_u_w_m2k * 4.0 * side * dz / heat_capacity_rate)
        t_out = t_amb_c + (t_in - t_amb_c) * cooling
        t_slice = (t_in + t_out) / 2.0
        p_abs = barometric_pressure(p.p_atm_pa, z, t_amb_c)
        rho_g = density(p_abs, t_slice, p.gas_molar_mass_g_mol)
        rho_o = density(p_abs, t_amb_c, AIR_MOLAR_MASS_G_MOL)
        draft += G * (rho_o - rho_g) * dz
        k_friction += p.chimney_friction * dz / (2.0 * side ** 5 * rho_g)
        temps.append(t_slice)
        rho_gas.append(rho_g)
        rho_out.append(rho_o)
        p_out.append(p_abs)
        t_in = t_out
    p_top = barometric_pressure(p.p_atm_pa, p.chimney_height_m, t_amb_c)
    rho_top = density(p_top, t_in, p.gas_molar_mass_g_mol)
    k_exit = 1.0 / (2.0 * p.chimney_top_side_m ** 4 * rho_top)
    return ChimneyState(dz=dz, z_mid=z_mid, side=sides, t_gas_c=tuple(temps), rho_gas=tuple(rho_gas),
                        rho_outside=tuple(rho_out), p_outside_abs=tuple(p_out), draft_pa=draft,
                        k_friction=k_friction, k_exit=k_exit, t_mean_c=sum(temps) / len(temps),
                        t_top_c=t_in, rho_top=rho_top)


# --------------------------------------------------------------------------- pressure balance
def operating_point(p, mass_flow: float, rpm: float, t_gas_c: float, t_amb_c: float) -> OperatingPoint:
    """Evaluate pressures, temperatures and draft for a given mass flow (steady or transient)."""
    k = _loss_coefficients(p)
    rho = density(p.p_atm_pa, t_gas_c, p.gas_molar_mass_g_mol)
    chimney = chimney_state(p, mass_flow, t_gas_c, t_amb_c)
    m2 = mass_flow ** 2

    q = mass_flow / rho
    fan_dp = (rho / FAN_REF_DENSITY) * (
        p.fan_shutoff_dp_pa * (rpm / p.fan_rated_rpm) ** 2 - k.fan_slope * q ** 2)
    loss_kiln = k.k_kiln * m2 / rho
    loss_fan_to_plate = k.k_fan_to_plate * m2 / rho
    plate_dp = k.k_plate_full * m2 / rho
    loss_plate = k.k_plate_loop * m2 / rho
    loss_restriction = k.k_restriction * m2 / rho
    loss_friction = chimney.k_friction * m2
    loss_exit = chimney.k_exit * m2

    p_fan_in = p.kiln_gauge_pa - loss_kiln
    p_fan_out = p_fan_in + fan_dp
    p1 = p_fan_out - loss_fan_to_plate
    p_base = p1 - loss_plate - loss_restriction
    residual = p_base + chimney.draft_pa - loss_friction - loss_exit

    return OperatingPoint(
        mass_flow_kg_s=mass_flow, q_m3_s=q, draft_pa=chimney.draft_pa, fan_dp_pa=fan_dp,
        plate_dp_pa=plate_dp, p_fan_in_pa=p_fan_in, p_fan_out_pa=p_fan_out, p1_pa=p1,
        p2_pa=p1 - plate_dp, p_chimney_base_pa=p_base, p_top_residual_pa=residual,
        loss_kiln_pa=loss_kiln, loss_fan_to_plate_pa=loss_fan_to_plate,
        loss_plate_permanent_pa=loss_plate, loss_restriction_pa=loss_restriction,
        loss_chimney_friction_pa=loss_friction, loss_exit_pa=loss_exit, t_gas_c=t_gas_c,
        t_chimney_mean_c=chimney.t_mean_c, t_chimney_top_c=chimney.t_top_c, rho_plate=rho,
        stalled=mass_flow <= 0.0)


def solve_steady(p, rpm: float, t_gas_c: float, t_amb_c: float, guess: float | None = None) -> OperatingPoint:
    """
    Steady-state flow for a fixed fan speed.

    ``guess`` is an optional starting mass flow (the previous answer); it only makes the solve
    faster, the result is the same.
    """
    k = _loss_coefficients(p)
    rho = density(p.p_atm_pa, t_gas_c, p.gas_molar_mass_g_mol)
    fan_gain = (rho / FAN_REF_DENSITY) * p.fan_shutoff_dp_pa * (rpm / p.fan_rated_rpm) ** 2
    fan_loss_term = k.fan_slope / (FAN_REF_DENSITY * rho)   # fan curve's Q^2 term, in m_dot^2 form
    fixed_resistance = ((k.k_kiln + k.k_fan_to_plate + k.k_plate_loop + k.k_restriction) / rho
                        + fan_loss_term)

    mass_flow = guess if guess is not None and guess > MIN_WARM_START_KG_S else DEFAULT_GUESS_KG_S
    for _ in range(MAX_ITERATIONS):
        chimney = chimney_state(p, mass_flow, t_gas_c, t_amb_c)
        driving = p.kiln_gauge_pa + chimney.draft_pa + fan_gain
        resistance = fixed_resistance + chimney.k_friction + chimney.k_exit
        target = math.sqrt(driving / resistance) if driving > 0.0 else 0.0
        if abs(target - mass_flow) < CONVERGENCE_KG_S:
            mass_flow = target
            break
        mass_flow += RELAXATION * (target - mass_flow)   # damping keeps the iteration from oscillating
    return operating_point(p, mass_flow, rpm, t_gas_c, t_amb_c)


def environment(p, time_s: float) -> tuple[float, float]:
    """Ambient temperature and exhaust gas temperature target at a given simulated time."""
    t_amb = p.t_amb_c + p.t_amb_swing_k * math.sin(2.0 * math.pi * time_s / p.t_amb_period_s)
    t_gas = p.t_gas_c + p.t_gas_swing_k * math.sin(2.0 * math.pi * time_s / p.t_gas_period_s)
    return t_amb, t_gas


class Plant:
    """Dynamic plant: fan speed, gas flow and gas temperature respond with lags."""

    def __init__(self, p, rpm: float, t_gas_c: float, t_amb_c: float):
        self.p = p
        self.rpm = rpm                  # real shaft speed
        self._rpm_reference = rpm       # ramp-limited reference the shaft lags behind
        self.t_gas_c = t_gas_c
        self.mass_flow = solve_steady(p, rpm, t_gas_c, t_amb_c).mass_flow_kg_s
        self._steady_guess = self.mass_flow

    def set_params(self, p) -> None:
        """Swap parameters at run time (slider moved). State is kept, so the plant responds smoothly."""
        self.p = p

    def step(self, dt: float, rpm_command: float, t_gas_target_c: float, t_amb_c: float) -> OperatingPoint:
        p = self.p
        max_change = p.drive_ramp_rpm_s * dt
        self._rpm_reference += max(-max_change, min(max_change, rpm_command - self._rpm_reference))
        self.rpm += (self._rpm_reference - self.rpm) * (1.0 - math.exp(-dt / p.motor_tau_s))
        self.t_gas_c += (t_gas_target_c - self.t_gas_c) * (1.0 - math.exp(-dt / p.gas_temp_tau_s))
        target = solve_steady(p, self.rpm, self.t_gas_c, t_amb_c, guess=self._steady_guess).mass_flow_kg_s
        self._steady_guess = target
        self.mass_flow += (target - self.mass_flow) * (1.0 - math.exp(-dt / p.flow_tau_s))
        return operating_point(p, self.mass_flow, self.rpm, self.t_gas_c, t_amb_c)
