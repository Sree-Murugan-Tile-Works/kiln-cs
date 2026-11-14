"""
Sensitivity and interaction analysis of the kiln process model.

Pure functions that run the same plant and closed loop the GUI uses and return plain data, so the
report (``sim.report``) and the tests share one source of numbers. Nothing here is site data: all
parameter values are the placeholders in ``sim.params``.
"""
import math

from sim.instruments import estimate_flow
from sim.loop import ClosedLoop
from sim.params import SPEC_BY_NAME, make_params, params_to_dict
from sim.plant import operating_point, solve_steady

TARGET_FLOW = 4.5          # m3/s, the default setpoint
REFERENCE_RPM = 900.0      # fan speed used for "flow at a fixed fan speed" comparisons
RPM_SEARCH_MAX = 3000.0
TRAVEL_FRACTION = 0.10     # tornado: move each slider by +/-10 % of its full travel
SETTLE_BAND = 0.02         # closed loop: settled when within 2 % of the target
WINDUP_HORIZON_S = 7200    # how long to wait for a wound-up integral to unwind

# Parameters that change the steady-state physics. Dynamics, instrument and controller parameters are
# covered by their own analyses (they do not move the steady operating point).
PHYSICAL_PARAMS = [
    "t_amb_c", "p_atm_pa", "t_gas_c", "kiln_gauge_pa", "gas_molar_mass_g_mol", "gas_cp_j_kg_k",
    "k_reuse", "reuse_extraction", "duct_diameter_m", "k_upstream", "plate_beta", "plate_cd",
    "fan_rated_rpm", "fan_shutoff_dp_pa", "fan_max_flow_m3s",
    "chimney_height_m", "chimney_diameter_m", "chimney_friction", "chimney_u_w_m2k",
]


def defaults() -> dict:
    return params_to_dict(make_params())


def build(base: dict, **changes):
    """Params from a base dict plus overrides (validated against the slider ranges)."""
    return make_params({**base, **changes})


# --------------------------------------------------------------------------- basic probes
def flow_at(p, rpm: float) -> float:
    return solve_steady(p, rpm, p.t_gas_c, p.t_amb_c).q_m3_s


def rpm_for_flow(p, target: float = TARGET_FLOW) -> float | None:
    """Fan speed that gives ``target`` m3/s: 0 if draft alone is enough, None if no speed can."""
    if flow_at(p, 0.0) >= target:
        return 0.0
    if flow_at(p, RPM_SEARCH_MAX) < target:
        return None
    lo, hi = 0.0, RPM_SEARCH_MAX
    for _ in range(60):
        mid = (lo + hi) / 2.0
        lo, hi = (mid, hi) if flow_at(p, mid) < target else (lo, mid)
    return (lo + hi) / 2.0


def metrics(p, target: float = TARGET_FLOW) -> dict:
    natural = solve_steady(p, 0.0, p.t_gas_c, p.t_amb_c)
    fixed = solve_steady(p, REFERENCE_RPM, p.t_gas_c, p.t_amb_c)
    return {
        "q_natural": natural.q_m3_s, "draft_pa": natural.draft_pa, "t_plate_c": natural.t_plate_c,
        "q_fixed_rpm": fixed.q_m3_s, "plate_dp_fixed": fixed.plate_dp_pa, "p1_fixed": fixed.p1_pa,
        "p2_fixed": fixed.p2_pa, "rpm_needed": rpm_for_flow(p, target),
    }


# --------------------------------------------------------------------------- baseline
def baseline_sweep(base: dict, rpms=(0, 200, 400, 600, 800, 1000, 1200, 1500)) -> list[dict]:
    p = build(base)
    rows = []
    for rpm in rpms:
        op = solve_steady(p, rpm, p.t_gas_c, p.t_amb_c)
        rows.append({"rpm": rpm, "q": op.q_m3_s, "draft": op.draft_pa, "fan_dp": op.fan_dp_pa,
                     "plate_dp": op.plate_dp_pa, "p1": op.p1_pa, "p2": op.p2_pa,
                     "t_plate": op.t_plate_c, "t_chim_mean": op.t_chimney_mean_c,
                     "p2_range_use": abs(op.p2_pa) / p.p_range_pa})
    return rows


# --------------------------------------------------------------------------- one-at-a-time sensitivity
def tornado(base: dict, travel: float = TRAVEL_FRACTION, target: float = TARGET_FLOW,
            relative: float | None = None) -> list[dict]:
    """
    Move each physical parameter and report the effect on the main outputs.

    By default each slider moves by +/-``travel`` of its full range (what you feel in the GUI).
    With ``relative`` set (e.g. 0.10) each parameter moves by +/-that fraction of its own value, which
    compares the physics independent of how wide a slider happens to be; parameters whose value is 0 are skipped.
    """
    centre = metrics(build(base), target)
    rows = []
    for name in PHYSICAL_PARAMS:
        spec = SPEC_BY_NAME[name]
        if relative is None:
            delta = travel * (spec.max - spec.min)
        elif base[name] == 0:
            continue
        else:
            delta = relative * abs(base[name])
        lo_value, hi_value = max(spec.min, base[name] - delta), min(spec.max, base[name] + delta)
        lo = metrics(build(base, **{name: lo_value}), target)
        hi = metrics(build(base, **{name: hi_value}), target)
        rows.append({"name": name, "label": spec.label, "unit": spec.unit, "base": base[name],
                     "lo_value": lo_value, "hi_value": hi_value, "lo": lo, "hi": hi, "centre": centre})
    rows.sort(key=lambda r: -_swing(r, "rpm_needed"))
    return rows


def _swing(row: dict, key: str) -> float:
    cap = RPM_SEARCH_MAX
    lo = row["lo"][key] if row["lo"][key] is not None else cap
    hi = row["hi"][key] if row["hi"][key] is not None else cap
    return abs(hi - lo)


# --------------------------------------------------------------------------- interactions
def fan_effect_vs_draft(base: dict, ambients=(-5, 15, 35), heights=(15, 30, 45)) -> list[dict]:
    """How much flow the fan adds (0 -> reference rpm) depending on the natural draft already present."""
    rows = []
    for t_amb in ambients:
        for height in heights:
            p = build(base, t_amb_c=t_amb, chimney_height_m=height)
            op0 = solve_steady(p, 0.0, p.t_gas_c, p.t_amb_c)
            q_fan = flow_at(p, REFERENCE_RPM)
            rows.append({"t_amb": t_amb, "height": height, "draft": op0.draft_pa, "q_natural": op0.q_m3_s,
                         "q_with_fan": q_fan, "fan_adds": q_fan - op0.q_m3_s})
    return rows


def rpm_needed_grid(base: dict, ambients, gas_temps, target: float = TARGET_FLOW) -> list[list[float | None]]:
    return [[rpm_for_flow(build(base, t_amb_c=a, t_gas_c=g), target) for g in gas_temps] for a in ambients]


def envelope_vs_ambient(base: dict, ambients) -> list[dict]:
    """Lowest and highest flow the loop can hold (fan at motor min/max) as the weather changes."""
    rows = []
    for t_amb in ambients:
        p = build(base, t_amb_c=t_amb)
        rows.append({"t_amb": t_amb, "q_min": flow_at(p, p.motor_min_rpm), "q_max": flow_at(p, p.motor_max_rpm),
                     "q_natural": flow_at(p, 0.0)})
    return rows


def reuse_interaction(base: dict, extractions=(0.0, 0.2, 0.4), losses=(0, 3, 9)) -> list[dict]:
    rows = []
    for ext in extractions:
        for loss in losses:
            p = build(base, reuse_extraction=ext, k_reuse=loss)
            op = solve_steady(p, REFERENCE_RPM, p.t_gas_c, p.t_amb_c)
            nat = solve_steady(p, 0.0, p.t_gas_c, p.t_amb_c)
            rows.append({"extraction": ext, "k_reuse": loss, "t_plate": op.t_plate_c, "q_natural": nat.q_m3_s,
                         "q_fixed_rpm": op.q_m3_s, "p1": op.p1_pa, "p2": op.p2_pa, "plate_dp": op.plate_dp_pa,
                         "rpm_needed": rpm_for_flow(p)})
    return rows


def plate_beta_study(base: dict, betas=(0.4, 0.5, 0.6, 0.7)) -> list[dict]:
    """Signal strength (plate dP) versus the permanent loss the fan must pay, and the instrument resolution."""
    rows = []
    for beta in betas:
        p = build(base, plate_beta=beta)
        rpm = rpm_for_flow(p)
        op = solve_steady(p, rpm or 0.0, p.t_gas_c, p.t_amb_c)
        dp_counts = op.plate_dp_pa / (2 * p.p_range_pa) * 6000
        rows.append({"beta": beta, "rpm_needed": rpm, "plate_dp": op.plate_dp_pa, "p2": op.p2_pa,
                     "p2_range_use": abs(op.p2_pa) / p.p_range_pa, "dp_counts": dp_counts,
                     "pct_per_count": 100.0 / (2 * dp_counts) if dp_counts > 0 else math.inf})
    return rows


def flow_resolution_vs_flow(base: dict, flows=(1.5, 2.5, 3.5, 4.5, 5.5)) -> list[dict]:
    """
    The square-root law: the plate dP (and so the counts the PLC sees) falls with flow squared, so one
    PLC count is a bigger slice of the flow at low flow. ``holdable`` says whether the fan/draft can
    actually hold that flow (it cannot go below what natural draft gives at the fan's minimum speed).
    """
    p = build(base)
    low, high = flow_at(p, p.motor_min_rpm), flow_at(p, p.motor_max_rpm)
    rows = []
    for q in flows:
        rho = solve_steady(p, 0.0, p.t_gas_c, p.t_amb_c).rho_plate
        op = operating_point(p, q * rho, 0.0, p.t_gas_c, p.t_amb_c)
        counts = op.plate_dp_pa / (2 * p.p_range_pa) * 6000
        rows.append({"q": q, "holdable": low <= q <= high, "plate_dp": op.plate_dp_pa, "dp_counts": counts,
                     "pct_per_count": 100.0 / (2 * counts) if counts > 0 else math.inf})
    return rows


# --------------------------------------------------------------------------- measurement errors
def true_flow_when_controller_holds_setpoint(base: dict, target: float = TARGET_FLOW, **assumptions) -> float:
    """
    The controller adjusts the fan until ITS flow estimate equals the setpoint. Because its estimate
    can be wrong (Cd, gas molar mass), the true flow ends up elsewhere. ``assumptions`` may include
    est_cd_error_pct, est_molar_mass_g_mol, and transmitter offsets p1_offset/p2_offset (Pa), t_offset (degC).
    """
    offsets = {k: assumptions.pop(k, 0.0) for k in ("p1_offset", "p2_offset", "t_offset")}
    p = build(base, **assumptions)

    def estimate(rpm: float) -> tuple[float, float]:
        op = solve_steady(p, rpm, p.t_gas_c, p.t_amb_c)
        est = estimate_flow(p, op.p1_pa + offsets["p1_offset"], op.p2_pa + offsets["p2_offset"],
                            op.t_plate_c + offsets["t_offset"])
        return est, op.q_m3_s

    lo, hi = 0.0, RPM_SEARCH_MAX
    for _ in range(60):
        mid = (lo + hi) / 2.0
        lo, hi = (mid, hi) if estimate(mid)[0] < target else (lo, mid)
    return estimate((lo + hi) / 2.0)[1]


def estimate_error_table(base: dict) -> dict:
    cd_errors, molar_masses = (-5, 0, 5, 10), (26.0, 28.5, 31.0)
    cd_table = {(cd, m): true_flow_when_controller_holds_setpoint(base, est_cd_error_pct=cd, est_molar_mass_g_mol=m)
                for cd in cd_errors for m in molar_masses}
    drift = {name: {off: true_flow_when_controller_holds_setpoint(base, **{name: off}) for off in offs}
             for name, offs in (("p1_offset", (-30, -10, 10, 30)), ("p2_offset", (-30, -10, 10, 30)),
                                ("t_offset", (-30, -10, 10, 30)))}
    return {"cd_errors": cd_errors, "molar_masses": molar_masses, "cd_table": cd_table, "drift": drift}


# --------------------------------------------------------------------------- closed loop
def _quiet(base: dict, **changes):
    return build(base, p_noise_pa=0.0, t_noise_c=0.0, **changes)


def _run(loop: ClosedLoop, seconds: float) -> list[dict]:
    return [loop.step() for _ in range(round(seconds / loop.p.scan_interval_s))]


def step_metrics(records: list[dict], t_step: float, start: float, target: float) -> dict:
    """Rise time (10-90 %), overshoot and settling time of the TRUE flow after a setpoint step."""
    after = [r for r in records if r["time_s"] > t_step]
    span = target - start
    def first_time(level):
        for r in after:
            if (r["flow_true_m3s"] - start) / span >= level:
                return r["time_s"] - t_step
        return math.nan
    peak = max(r["flow_true_m3s"] for r in after) if span > 0 else min(r["flow_true_m3s"] for r in after)
    overshoot = max(0.0, (peak - target) / span * 100.0) if span > 0 else 0.0
    settle = 0.0
    for r in after:
        if abs(r["flow_true_m3s"] - target) > SETTLE_BAND * target:
            settle = r["time_s"] - t_step
    never = abs(after[-1]["flow_true_m3s"] - target) > SETTLE_BAND * target
    return {"rise_s": first_time(0.9) - first_time(0.1), "overshoot_pct": overshoot,
            "settle_s": math.inf if never else settle}


def pid_tuning_grid(base: dict, kps=(0.5, 1.5, 3.0), kis=(0.05, 0.2, 0.5), start=4.0, target=5.0) -> list[dict]:
    rows = []
    for kp in kps:
        for ki in kis:
            loop = ClosedLoop(_quiet(base, kp=kp, ki=ki), f"PID {start}")
            _run(loop, 300)
            loop.set_command(f"PID {target}")
            records = _run(loop, 600)
            rows.append({"kp": kp, "ki": ki, **step_metrics(records, 300.0, start, target)})
    return rows


def lag_study(base: dict, start=4.0, target=5.0) -> list[dict]:
    """How plant/instrument/scan time constants limit the loop, at the default gains."""
    rows = []
    for name, values in (("flow_tau_s", (1.0, 3.0, 10.0, 30.0)), ("motor_tau_s", (0.5, 2.0, 8.0, 20.0)),
                         ("sensor_tau_s", (0.5, 1.0, 5.0, 10.0)), ("scan_interval_s", (0.5, 1.0, 2.0, 5.0))):
        for value in values:
            loop = ClosedLoop(_quiet(base, **{name: value}), f"PID {start}")
            _run(loop, 300)
            loop.set_command(f"PID {target}")
            records = _run(loop, 900)
            rows.append({"param": name, "value": value, **step_metrics(records, 300.0, start, target)})
    return rows


def disturbance_response(base: dict, t_amb_after: float = 5.0, target: float = TARGET_FLOW) -> dict:
    """A cold front hits while the loop holds the setpoint: how far does the true flow move, and how fast does it recover."""
    loop = ClosedLoop(_quiet(base), f"PID {target}")
    _run(loop, 300)
    colder = build(base, t_amb_c=t_amb_after, p_noise_pa=0.0, t_noise_c=0.0)
    loop.set_params(colder)
    records = _run(loop, 600)
    deviation = max(abs(r["flow_true_m3s"] - target) for r in records)
    recovered = 0.0
    for r in records:
        if abs(r["flow_true_m3s"] - target) > SETTLE_BAND * target:
            recovered = r["time_s"] - 300.0
    return {"peak_deviation": deviation, "recovery_s": recovered, "records": records,
            "natural_after": records[-1]["flow_natural_only_m3s"], "rpm_after": records[-1]["rpm_commanded"]}


def windup_recovery(base: dict) -> dict:
    """Seconds to reach the setpoint after sitting 10 minutes at the fan's minimum speed, with and without anti-windup."""
    result = {}
    for flag in (1.0, 0.0):
        loop = ClosedLoop(_quiet(base, anti_windup=flag), "PID 1.0")      # unreachable: below natural flow
        _run(loop, 600)
        loop.set_command(f"PID {TARGET_FLOW}")
        seconds = math.inf
        for i, r in enumerate(_run(loop, WINDUP_HORIZON_S), start=1):
            if abs(r["flow_true_m3s"] - TARGET_FLOW) < SETTLE_BAND * 2.5 * TARGET_FLOW:
                seconds = i * loop.p.scan_interval_s
                break
        result["with" if flag else "without"] = seconds
    return result


def step_records(base: dict, kp: float, ki: float, start=4.0, target=5.0, hold_s=300, run_s=600) -> list[dict]:
    """Time series of a setpoint step, for plotting. The step happens at ``hold_s``."""
    loop = ClosedLoop(_quiet(base, kp=kp, ki=ki), f"PID {start}")
    _run(loop, hold_s)
    loop.set_command(f"PID {target}")
    return _run(loop, run_s)
