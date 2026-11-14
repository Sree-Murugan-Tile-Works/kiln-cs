"""
Parameter registry for the kiln process simulation.

Every tunable number lives in ``PARAM_SPECS``. That one list is the single source for:
  * the default value (placeholders -- "generally meaningful", NOT measured site data),
  * the allowed range (used to validate input and to build GUI sliders),
  * the unit and a plain-language description (shown next to each slider).

``Params`` is a dataclass generated from the registry, so there is no second list of
defaults to keep in sync.

All values are SI unless the unit column says otherwise (Pa, m, kg/m3, degC for temperatures).
"""
from dataclasses import dataclass, make_dataclass, field, fields
from typing import Any


@dataclass(frozen=True)
class ParamSpec:
    name: str
    group: str
    label: str
    unit: str
    default: float
    min: float
    max: float
    step: float
    help: str
    kind: str = "float"          # "float" -> slider, "bool" -> checkbox


# Order here is the order the GUI shows the groups and sliders.
PARAM_SPECS: list[ParamSpec] = [
    # ---------------------------------------------------------------- Weather
    ParamSpec("t_amb_c", "Weather", "Ambient temperature", "degC", 25, -10, 45, 0.5,
              "Outside air temperature. Colder air is denser, so it pushes harder on the chimney (more draft)."),
    ParamSpec("t_amb_swing_k", "Weather", "Ambient swing", "K", 0, 0, 15, 0.5,
              "Size of a slow sinusoidal weather swing added to the ambient temperature (0 = steady)."),
    ParamSpec("t_amb_period_s", "Weather", "Ambient swing period", "s", 600, 60, 3600, 30,
              "Time for one full weather swing."),
    ParamSpec("p_atm_pa", "Weather", "Atmospheric pressure", "Pa", 101325, 95000, 105000, 100,
              "Barometric pressure. Sets gas density and the absolute level of P1/P2."),

    # ------------------------------------------------------------- Kiln / gas
    ParamSpec("t_gas_c", "Kiln gas", "Kiln gas temperature (before heat reuse)", "degC", 250, 20, 500, 5,
              "Flue gas temperature leaving the firing zone, before the heat-reuse tunnels. Hotter gas is lighter, so more draft."),
    ParamSpec("t_gas_swing_k", "Kiln gas", "Kiln gas temperature swing", "K", 0, 0, 80, 1,
              "Size of a slow sinusoidal swing in kiln gas temperature (firing cycle, 0 = steady)."),
    ParamSpec("t_gas_period_s", "Kiln gas", "Gas swing period", "s", 900, 60, 3600, 30,
              "Time for one full kiln-temperature swing."),
    ParamSpec("kiln_gauge_pa", "Kiln gas", "Kiln gauge pressure", "Pa", 0, -50, 50, 1,
              "Pressure inside the kiln relative to the room. Positive pushes gas out, negative holds it in."),
    ParamSpec("gas_molar_mass_g_mol", "Kiln gas", "Gas molar mass", "g/mol", 28.5, 24, 32, 0.1,
              "Mean molecular weight of the flue gas (wood smoke: N2, CO2, water vapour). Sets gas density."),
    ParamSpec("gas_cp_j_kg_k", "Kiln gas", "Gas specific heat", "J/kg/K", 1100, 900, 1300, 10,
              "Heat capacity of the flue gas. Sets how fast the gas cools along the chimney."),

    # ------------------------------------------------------------ Duct / reuse
    ParamSpec("duct_diameter_m", "Duct", "Duct diameter", "m", 1.0, 0.5, 1.5, 0.05,
              "Diameter of the duct that holds the orifice plate and leads to the fan."),
    ParamSpec("k_reuse", "Kiln gas", "Heat-reuse tunnel loss", "-", 3.0, 0, 15, 0.1,
              "Loss coefficient of the kiln's internal heat-reuse tunnels (before the plate). Raises suction at P1."),
    ParamSpec("reuse_extraction", "Kiln gas", "Heat extracted by reuse", "fraction", 0.2, 0, 0.6, 0.01,
              "Fraction of the gas heat (above ambient) taken out inside the kiln tunnels before the plate. Colder gas at the plate = less draft."),
    ParamSpec("k_upstream", "Duct", "Duct loss (kiln exit to plate)", "-", 2.0, 0, 10, 0.1,
              "Dimensionless loss coefficient of the duct between the kiln tunnels and the plate."),

    # --------------------------------------------------------------- Plate
    ParamSpec("plate_beta", "Orifice plate", "Plate beta (bore / duct)", "-", 0.6, 0.3, 0.75, 0.01,
              "Bore diameter divided by duct diameter. Smaller bore = bigger pressure drop and more permanent loss."),
    ParamSpec("plate_cd", "Orifice plate", "Plate discharge coefficient", "-", 0.61, 0.55, 0.70, 0.005,
              "True discharge coefficient of the plate. The controller's estimate can differ (see Controller)."),

    # ----------------------------------------------------------------- Fan
    ParamSpec("fan_rated_rpm", "Fan", "Fan rated speed", "rpm", 1500, 1000, 3000, 50,
              "Speed at which the fan curve below applies. Other speeds follow the fan affinity laws."),
    ParamSpec("fan_shutoff_dp_pa", "Fan", "Fan shut-off pressure", "Pa", 600, 100, 1500, 10,
              "Pressure the fan can build at rated speed with no flow (top of the fan curve)."),
    ParamSpec("fan_max_flow_m3s", "Fan", "Fan free-delivery flow", "m3/s", 12, 4, 30, 0.5,
              "Flow at which the fan curve falls to zero pressure at rated speed. Sets the curve slope."),
    ParamSpec("motor_min_rpm", "Fan", "Motor minimum speed", "rpm", 200, 0, 600, 10,
              "Lowest speed the drive will command while running. 0 lets the fan stop when draft is enough."),
    ParamSpec("motor_max_rpm", "Fan", "Motor maximum speed", "rpm", 1500, 600, 3000, 50,
              "Highest speed the drive will command."),
    ParamSpec("pid_min_rpm", "Fan", "PID range minimum", "rpm", 200, 0, 1000, 10,
              "PID output 0 % maps to this speed."),
    ParamSpec("pid_max_rpm", "Fan", "PID range maximum", "rpm", 1500, 600, 3000, 50,
              "PID output 100 % maps to this speed."),
    ParamSpec("drive_ramp_rpm_s", "Fan", "Drive ramp rate", "rpm/s", 300, 20, 1000, 10,
              "How fast the drive lets the speed reference change."),
    ParamSpec("motor_tau_s", "Fan", "Motor/fan lag", "s", 2.0, 0.1, 20, 0.1,
              "First-order lag between the speed reference and the real shaft speed (inertia)."),

    # ------------------------------------------------------------- Chimney
    ParamSpec("chimney_height_m", "Chimney", "Chimney height", "m", 30, 5, 60, 1,
              "Taller chimney = more buoyancy pressure (stack effect)."),
    ParamSpec("chimney_diameter_m", "Chimney", "Chimney diameter", "m", 1.2, 0.5, 2.5, 0.05,
              "Wider chimney = lower velocity and less friction, but more surface to lose heat."),
    ParamSpec("chimney_friction", "Chimney", "Chimney friction factor", "-", 0.02, 0.005, 0.06, 0.001,
              "Darcy friction factor of the chimney wall (rough brick is higher)."),
    ParamSpec("chimney_u_w_m2k", "Chimney", "Chimney wall heat loss", "W/m2/K", 3.0, 0, 15, 0.5,
              "Heat-loss coefficient of the chimney wall. Higher = gas cools more on the way up = less draft."),

    # ------------------------------------------------------------ Dynamics
    ParamSpec("flow_tau_s", "Dynamics", "Gas flow lag", "s", 3.0, 0.5, 30, 0.5,
              "How quickly the gas column speeds up or slows down after a change (gas inertia)."),
    ParamSpec("gas_temp_tau_s", "Dynamics", "Gas temperature lag", "s", 60, 1, 600, 5,
              "How quickly the gas temperature follows the kiln (thermal mass of the duct)."),

    # --------------------------------------------------------- Instruments
    ParamSpec("p_range_pa", "Instruments", "Pressure transmitter range (+/-)", "Pa", 500, 100, 2000, 50,
              "Each pressure transmitter spans -range..+range, mapped to 0..6000 PLC counts."),
    ParamSpec("t_range_max_c", "Instruments", "Temperature transmitter max", "degC", 600, 300, 800, 10,
              "The temperature transmitter spans 0..max, mapped to 0..6000 PLC counts."),
    ParamSpec("p_noise_pa", "Instruments", "Pressure noise", "Pa", 1.0, 0, 10, 0.1,
              "Standard deviation of random noise on P1 and P2."),
    ParamSpec("t_noise_c", "Instruments", "Temperature noise", "degC", 0.3, 0, 5, 0.1,
              "Standard deviation of random noise on the duct temperature."),
    ParamSpec("sensor_tau_s", "Instruments", "Sensor lag", "s", 1.0, 0.1, 10, 0.1,
              "First-order response time of the transmitters and impulse lines."),

    # ---------------------------------------------------------- Controller
    ParamSpec("est_cd_error_pct", "Controller", "Plate Cd error assumed", "%", 0, -10, 10, 0.5,
              "How wrong the controller's flow calculation is about the plate Cd (0 = perfect)."),
    ParamSpec("est_molar_mass_g_mol", "Controller", "Gas molar mass assumed", "g/mol", 28.5, 24, 32, 0.1,
              "Molar mass the controller's flow calculation assumes (differs from the true gas = estimate error)."),
    ParamSpec("flow_span_m3s", "Controller", "Flow scaling span", "m3/s", 8, 4, 15, 0.5,
              "Flow that counts as 100 % when normalising PID error. Changes the effective PID gain."),
    ParamSpec("kp", "Controller", "PID Kp", "-", 1.5, 0, 10, 0.05,
              "Proportional gain on the normalised flow error."),
    ParamSpec("ki", "Controller", "PID Ki", "1/s", 0.20, 0, 2, 0.01,
              "Integral gain on the normalised flow error."),
    ParamSpec("kd", "Controller", "PID Kd", "s", 0.0, 0, 10, 0.1,
              "Derivative gain on the normalised flow error."),
    ParamSpec("scan_interval_s", "Controller", "Scan interval", "s", 1.0, 0.2, 5, 0.1,
              "How often the controller reads the sensors and updates the fan speed."),
    ParamSpec("safe_rpm", "Controller", "Safe speed", "rpm", 600, 0, 1500, 10,
              "Fixed speed used on a sensor fault or a software OFF (the Pi never stops the fan)."),
    ParamSpec("anti_windup", "Controller", "Anti-windup", "", 1, 0, 1, 1,
              "Stop the integral term growing while the fan is at its speed limit.", kind="bool"),
]

SPEC_BY_NAME: dict[str, ParamSpec] = {s.name: s for s in PARAM_SPECS}

# The dataclass is generated from the registry so defaults are written down exactly once.
Params = make_dataclass(
    "Params",
    [(s.name, float, field(default=float(s.default))) for s in PARAM_SPECS],
    namespace={"__doc__": "Simulation parameters; fields and defaults come from PARAM_SPECS."},
)


def make_params(values: dict[str, Any] | None = None):
    """Build a Params object from overrides. Unknown names and out-of-range values raise ValueError."""
    values = values or {}
    unknown = set(values) - set(SPEC_BY_NAME)
    if unknown:
        raise ValueError(f"Unknown parameter(s): {sorted(unknown)}")
    for name, value in values.items():
        spec = SPEC_BY_NAME[name]
        if not spec.min <= float(value) <= spec.max:
            raise ValueError(f"{name}={value} is outside [{spec.min}, {spec.max}]")
    return Params(**{k: float(v) for k, v in values.items()})


def params_to_dict(params) -> dict[str, float]:
    return {f.name: getattr(params, f.name) for f in fields(params)}


def specs_as_dicts() -> list[dict[str, Any]]:
    """Registry as plain dicts, for the GUI to build its sliders from."""
    return [s.__dict__.copy() for s in PARAM_SPECS]
