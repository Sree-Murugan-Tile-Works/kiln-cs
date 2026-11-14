"""
Physical model of the kiln exhaust path:

    kiln -> duct -> orifice plate (P1 | P2, T) -> heat-reuse stages -> fan -> chimney -> atmosphere

How the flow is found
---------------------
Two things push gas through the path:
  * natural draft: ``draft = g * H * (rho_ambient - rho_chimney_mean)`` -- the hot, light gas in
    the chimney is buoyant against the heavier outside air (stack effect);
  * the fan, with a quadratic fan curve scaled by the affinity laws:
    ``dP_fan = (rho/rho_ref) * (dP_shutoff*(N/N_rated)^2 - c_f*Q^2)``.

Everything in between resists with ``dP = k * m_dot^2 / rho``. Balancing the pressures gives

    draft + fan_gain(N) = m_dot^2 * (sum_i k_i/rho_i + fan_slope term)

which is solved for the mass flow ``m_dot``. The fan gain is the speed-dependent part of the fan
curve, so the fan's effect on flow depends on how much natural draft exists -- the property the
real system has. The chimney gas cools as it rises (more at low flow), which changes the draft,
so the solve is a short damped fixed-point iteration.

Simplifications (deliberate; the model is for control behaviour, not design):
  * gas is treated as incompressible for the pressure balance (plate dP is ~1 % of atmospheric);
  * hydrostatic pressure differences inside the horizontal duct are ignored;
  * a stopped fan is a passive resistance (no windmilling); flow never reverses (it stalls at 0);
  * the plate's true flow uses the standard orifice equation; the controller's own flow estimate is
    separate (see ``instruments.estimate_flow``) and may be deliberately wrong.

P1 and P2 are returned as gauge pressures relative to the room, like the real
gauge-via-differential transmitters, so they go negative under suction.
"""
import math
from dataclasses import dataclass

from sim.gas import density, G, AIR_MOLAR_MASS_G_MOL, FAN_REF_DENSITY

MAX_ITERATIONS = 200
CONVERGENCE_KG_S = 1e-10
MIN_MASS_FLOW_FOR_COOLING = 1e-6   # kg/s, avoids dividing by zero in the chimney heat-loss term
PERMANENT_LOSS_EXPONENT = 1.9      # permanent loss fraction of the plate dP = 1 - beta**1.9 (common approximation)


@dataclass(frozen=True)
class OperatingPoint:
    """Everything the plant can say about one instant. Pressures are gauge (room = 0)."""
    mass_flow_kg_s: float
    q_m3_s: float            # true volumetric flow at the plate (gas conditions at the plate)
    draft_pa: float          # natural draft available from the chimney
    fan_dp_pa: float         # pressure the fan adds (negative if it is a net restriction)
    plate_dp_pa: float       # differential pressure across the plate (P1 - P2)
    p1_pa: float
    p2_pa: float
    t_plate_c: float
    t_fan_in_c: float
    t_chimney_mean_c: float
    t_chimney_top_c: float
    rho_plate: float
    stalled: bool            # True when nothing is pushing gas forward (no flow)


def _area(diameter_m: float) -> float:
    return math.pi / 4.0 * diameter_m ** 2


@dataclass(frozen=True)
class _LossCoefficients:
    """Resistance coefficients, each in dP = k * m_dot^2 / rho form."""
    k_upstream: float
    k_plate_full: float      # full plate dP (what the transmitters see)
    k_plate_loop: float      # permanent loss part (what the fan/draft must overcome)
    k_reuse: float
    k_chimney: float         # friction + exit loss
    fan_slope: float         # c_f in the fan curve, Pa / (m3/s)^2


def _loss_coefficients(p) -> _LossCoefficients:
    a_duct = _area(p.duct_diameter_m)
    a_chim = _area(p.chimney_diameter_m)
    a_bore = _area(p.plate_beta * p.duct_diameter_m)
    k_plate_full = (1.0 - p.plate_beta ** 4) / (2.0 * p.plate_cd ** 2 * a_bore ** 2)
    permanent_fraction = 1.0 - p.plate_beta ** PERMANENT_LOSS_EXPONENT
    chimney_k = p.chimney_friction * p.chimney_height_m / p.chimney_diameter_m + 1.0   # +1 = exit loss
    return _LossCoefficients(
        k_upstream=p.k_upstream / (2.0 * a_duct ** 2),
        k_plate_full=k_plate_full,
        k_plate_loop=k_plate_full * permanent_fraction,
        k_reuse=p.k_reuse / (2.0 * a_duct ** 2),
        k_chimney=chimney_k / (2.0 * a_chim ** 2),
        fan_slope=p.fan_shutoff_dp_pa / p.fan_max_flow_m3s ** 2,
    )


def _chimney_temps(p, mass_flow: float, t_base_c: float, t_amb_c: float) -> tuple[float, float]:
    """Mean and top gas temperature in the chimney. The gas cools exponentially towards ambient."""
    m = max(mass_flow, MIN_MASS_FLOW_FOR_COOLING)
    x = p.chimney_u_w_m2k * math.pi * p.chimney_diameter_m * p.chimney_height_m / (m * p.gas_cp_j_kg_k)
    top_factor = math.exp(-x)
    mean_factor = (1.0 - top_factor) / x if x > 1e-9 else 1.0
    return (t_amb_c + (t_base_c - t_amb_c) * mean_factor,
            t_amb_c + (t_base_c - t_amb_c) * top_factor)


def operating_point(p, mass_flow: float, rpm: float, t_gas_c: float, t_amb_c: float) -> OperatingPoint:
    """Evaluate pressures, temperatures and draft for a given mass flow (steady or transient)."""
    k = _loss_coefficients(p)
    rho_plate = density(p.p_atm_pa, t_gas_c, p.gas_molar_mass_g_mol)
    t_fan_in = t_gas_c - p.reuse_extraction * (t_gas_c - t_amb_c)
    rho_fan = density(p.p_atm_pa, t_fan_in, p.gas_molar_mass_g_mol)
    t_mean, t_top = _chimney_temps(p, mass_flow, t_fan_in, t_amb_c)
    rho_amb = density(p.p_atm_pa, t_amb_c, AIR_MOLAR_MASS_G_MOL)
    rho_chim = density(p.p_atm_pa, t_mean, p.gas_molar_mass_g_mol)

    draft = G * p.chimney_height_m * (rho_amb - rho_chim)
    q_fan = mass_flow / rho_fan
    fan_dp = (rho_fan / FAN_REF_DENSITY) * (
        p.fan_shutoff_dp_pa * (rpm / p.fan_rated_rpm) ** 2 - k.fan_slope * q_fan ** 2)
    plate_dp = k.k_plate_full * mass_flow ** 2 / rho_plate
    p1 = p.kiln_gauge_pa - k.k_upstream * mass_flow ** 2 / rho_plate

    return OperatingPoint(
        mass_flow_kg_s=mass_flow, q_m3_s=mass_flow / rho_plate, draft_pa=draft, fan_dp_pa=fan_dp,
        plate_dp_pa=plate_dp, p1_pa=p1, p2_pa=p1 - plate_dp, t_plate_c=t_gas_c, t_fan_in_c=t_fan_in,
        t_chimney_mean_c=t_mean, t_chimney_top_c=t_top, rho_plate=rho_plate, stalled=mass_flow <= 0.0)


def solve_steady(p, rpm: float, t_gas_c: float, t_amb_c: float) -> OperatingPoint:
    """Steady-state flow for a fixed fan speed and temperatures."""
    k = _loss_coefficients(p)
    rho_plate = density(p.p_atm_pa, t_gas_c, p.gas_molar_mass_g_mol)
    t_fan_in = t_gas_c - p.reuse_extraction * (t_gas_c - t_amb_c)
    rho_fan = density(p.p_atm_pa, t_fan_in, p.gas_molar_mass_g_mol)
    rho_reuse = density(p.p_atm_pa, (t_gas_c + t_fan_in) / 2.0, p.gas_molar_mass_g_mol)
    rho_amb = density(p.p_atm_pa, t_amb_c, AIR_MOLAR_MASS_G_MOL)
    fan_gain = (rho_fan / FAN_REF_DENSITY) * p.fan_shutoff_dp_pa * (rpm / p.fan_rated_rpm) ** 2
    fan_loss_term = k.fan_slope / (FAN_REF_DENSITY * rho_fan)   # fan curve's Q^2 term, in m_dot^2 form

    mass_flow = 1.0   # starts on the "warm chimney" branch, not the (unphysical) cold-chimney one
    for _ in range(MAX_ITERATIONS):
        t_mean, _ = _chimney_temps(p, mass_flow, t_fan_in, t_amb_c)
        rho_chim = density(p.p_atm_pa, t_mean, p.gas_molar_mass_g_mol)
        draft = G * p.chimney_height_m * (rho_amb - rho_chim)
        resistance = ((k.k_upstream + k.k_plate_loop) / rho_plate
                      + k.k_reuse / rho_reuse + k.k_chimney / rho_chim + fan_loss_term)
        driving = draft + fan_gain
        target = math.sqrt(driving / resistance) if driving > 0.0 else 0.0
        if abs(target - mass_flow) < CONVERGENCE_KG_S:
            mass_flow = target
            break
        mass_flow = 0.5 * mass_flow + 0.5 * target   # damping keeps the iteration from oscillating
    return operating_point(p, mass_flow, rpm, t_gas_c, t_amb_c)


def environment(p, time_s: float) -> tuple[float, float]:
    """Ambient temperature and kiln gas temperature target at a given simulated time."""
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

    def set_params(self, p) -> None:
        """Swap parameters at run time (slider moved). State is kept, so the plant responds smoothly."""
        self.p = p

    def step(self, dt: float, rpm_command: float, t_gas_target_c: float, t_amb_c: float) -> OperatingPoint:
        p = self.p
        max_change = p.drive_ramp_rpm_s * dt
        self._rpm_reference += max(-max_change, min(max_change, rpm_command - self._rpm_reference))
        self.rpm += (self._rpm_reference - self.rpm) * (1.0 - math.exp(-dt / p.motor_tau_s))
        self.t_gas_c += (t_gas_target_c - self.t_gas_c) * (1.0 - math.exp(-dt / p.gas_temp_tau_s))
        target = solve_steady(p, self.rpm, self.t_gas_c, t_amb_c).mass_flow_kg_s
        self.mass_flow += (target - self.mass_flow) * (1.0 - math.exp(-dt / p.flow_tau_s))
        return operating_point(p, self.mass_flow, self.rpm, self.t_gas_c, t_amb_c)
