"""
Generate the parameter-interaction report: ``python -m sim.report`` (repo root, venv active).

Writes ``project/simulation-report.md`` and the figures in ``project/simulation-report/``. Every number
in the text comes from ``sim.analysis`` and ``sim.profile`` (the same model the GUI runs), so rerunning
after a change to the model or the placeholder defaults keeps the report honest.
"""
import math
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sim import analysis as an
from sim.params import SPEC_BY_NAME
from sim.plant import solve_steady
from sim.profile import build_profile

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "project" / "simulation-report.md"
FIG_DIR = ROOT / "project" / "simulation-report"
FIG_REL = "simulation-report"

BLUE, ORANGE, GREEN, RED, GREY, MAGENTA = "#2a6fdb", "#d2691e", "#1f8a4c", "#c8372d", "#6b7686", "#a8327f"
SITE = {"p1": 119.2, "p2": 87.0, "t_gas": 130.4, "rpm": 380.0, "screen_value": 40.33}   # LabVIEW screen, 17-03-2026
STEP_START, STEP_TARGET = 3.2, 3.8
FT_PER_M = 3.28084


# --------------------------------------------------------------------------- small helpers
def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def rpm(v) -> str:
    return f"n/a (beyond {an.RPM_SEARCH_MAX:.0f})" if v is None else f"{v:.0f}"


def secs(v: float) -> str:
    return "never (within the test)" if math.isinf(v) else f"{v:.0f} s"


def num(v, digits: int = 1) -> str:
    return "–" if v is None else f"{v:.{digits}f}"


def value(name: str, v: float) -> str:
    spec = SPEC_BY_NAME[name]
    text = f"{v:.3g}" if abs(v) < 1000 else f"{v:.0f}"
    return f"{text} {spec.unit}".strip().rstrip("-").strip()


def swing(row: dict) -> float:
    cap = an.RPM_SEARCH_MAX
    lo = row["lo"]["rpm_needed"] if row["lo"]["rpm_needed"] is not None else cap
    hi = row["hi"]["rpm_needed"] if row["hi"]["rpm_needed"] is not None else cap
    return abs(hi - lo)


def save(fig, name: str) -> str:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(FIG_DIR / name, dpi=130)
    plt.close(fig)
    return f"![{name}]({FIG_REL}/{name})"


# --------------------------------------------------------------------------- figures
def fig_flow_vs_rpm(base: dict) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    speeds = list(range(0, 451, 15))
    for ax, name, values, title, legend_title in (
            (axes[0], "t_amb_c", (10, 25, 40), "Weather: outside air temperature (°C)", "outside T °C"),
            (axes[1], "chimney_height_m", (20, 38.1, 55), "Chimney height (m)", "chimney m")):
        for v, colour in zip(values, (BLUE, GREEN, ORANGE)):
            p = an.build(base, **{name: v})
            ax.plot(speeds, [an.flow_at(p, s) for s in speeds], color=colour, lw=2, label=f"{v:g}")
        ax.axhline(an.TARGET_FLOW, color=GREY, ls="--", lw=1)
        ax.axvspan(base["resonance_low_rpm"], base["resonance_high_rpm"], color=RED, alpha=.12)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("fan speed (rpm); shaded: resonance band")
        ax.legend(title=legend_title, fontsize=8)
        ax.grid(alpha=.3)
    axes[0].set_ylabel("true flow through the plate (m³/s)")
    axes[0].text(5, an.TARGET_FLOW + 0.05, "setpoint", color=GREY, fontsize=8)
    return save(fig, "flow_vs_rpm.png")


def fig_heatmap(ambients, gas_temps, grid) -> str:
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    data = [[math.nan if v is None else v for v in row] for row in grid]
    image = ax.imshow(data, cmap="YlOrRd", aspect="auto", origin="lower")
    ax.set_xticks(range(len(gas_temps)), [f"{g}" for g in gas_temps])
    ax.set_yticks(range(len(ambients)), [f"{a}" for a in ambients])
    ax.set_xlabel("exhaust gas temperature (°C)")
    ax.set_ylabel("outside air temperature (°C)")
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            ax.text(j, i, "n/a" if v is None else f"{v:.0f}", ha="center", va="center", fontsize=8)
    fig.colorbar(image, label=f"fan rpm needed for {an.TARGET_FLOW} m³/s")
    return save(fig, "rpm_needed_heatmap.png")


def fig_tornado(rows) -> str:
    rows = rows[:12][::-1]
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    centre = rows[0]["centre"]["rpm_needed"]
    cap = an.RPM_SEARCH_MAX
    for i, r in enumerate(rows):
        lo, hi = r["lo"]["rpm_needed"], r["hi"]["rpm_needed"]
        ax.barh(i, (cap if lo is None else lo) - centre, color=BLUE, height=.38, label="−10 %" if i == 0 else None)
        ax.barh(i, (cap if hi is None else hi) - centre, color=ORANGE, height=.38, label="+10 %" if i == 0 else None)
    ax.set_yticks(range(len(rows)), [r["label"] for r in rows], fontsize=8)
    ax.axvline(0, color="black", lw=.8)
    ax.set_xlabel(f"change in fan rpm needed for {an.TARGET_FLOW} m³/s (centre {centre:.0f} rpm)")
    ax.legend(title="parameter moved", fontsize=8)
    ax.grid(axis="x", alpha=.3)
    return save(fig, "tornado_relative.png")


def fig_envelope(ambients, rows) -> str:
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.fill_between(ambients, [r["q_min"] for r in rows], [r["q_max"] for r in rows], color=BLUE, alpha=.2,
                    label="flow the loop can hold")
    ax.plot(ambients, [r["q_natural"] for r in rows], color=GREEN, ls="--", label="natural draft alone (fan stopped)")
    ax.plot(ambients, [r["q_min"] for r in rows], color=BLUE)
    ax.plot(ambients, [r["q_max"] for r in rows], color=BLUE)
    ax.axhline(an.TARGET_FLOW, color=GREY, ls="--", lw=1)
    ax.text(ambients[0], an.TARGET_FLOW + .04, "setpoint", color=GREY, fontsize=8)
    ax.set_xlabel("outside air temperature (°C)")
    ax.set_ylabel("flow (m³/s)")
    ax.legend(fontsize=8, loc="center right")
    ax.grid(alpha=.3)
    return save(fig, "operating_envelope.png")


def fig_pressures(base: dict) -> str:
    p = an.build(base)
    speeds = list(range(0, 451, 10))
    ops = [solve_steady(p, s, p.t_gas_c, p.t_amb_c) for s in speeds]
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.axhspan(0, p.p_range_pa, color=GREEN, alpha=.08)
    ax.text(5, p.p_range_pa - 22, f"what the 0–{p.p_range_pa:.0f} Pa transmitters can read", color=GREEN, fontsize=8)
    ax.plot(speeds, [o.p1_pa for o in ops], color=BLUE, lw=2, label="P1 (before the plate)")
    ax.plot(speeds, [o.p2_pa for o in ops], color=MAGENTA, lw=2, label="P2 (after the plate)")
    ax.plot(speeds, [o.p_fan_in_pa for o in ops], color=RED, lw=1.5, ls="--", label="fan inlet")
    ax.plot(speeds, [o.p_chimney_base_pa for o in ops], color=GREY, lw=1.5, ls="--", label="chimney base")
    ax.scatter([SITE["rpm"]] * 2, [SITE["p1"], SITE["p2"]], color="black", zorder=5, label="site reading (17-03-2026)")
    ax.axvspan(base["resonance_low_rpm"], base["resonance_high_rpm"], color=RED, alpha=.12)
    ax.axhline(0, color="black", lw=.8)
    ax.set_xlabel("fan speed (rpm); shaded: resonance band")
    ax.set_ylabel("gauge pressure (Pa)")
    ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(0.0, 0.86))
    ax.grid(alpha=.3)
    return save(fig, "pressures_vs_rpm.png")


def fig_chimney(base: dict) -> str:
    p = an.build(base)
    profile = build_profile(p, solve_steady(p, an.REFERENCE_RPM, p.t_gas_c, p.t_amb_c), p.t_amb_c)
    z = [s["z_m"] for s in profile["chimney"]]
    fig, axes = plt.subplots(1, 4, figsize=(11, 4.0), sharey=True)
    series = (("side_m", "inside side (m)", GREY), ("t_c", "gas temperature (°C)", RED),
              ("v_m_s", "gas velocity (m/s)", BLUE), ("p_gauge_local_pa", "pressure vs outside air\nat the same height (Pa)", MAGENTA))
    for ax, (key, title, colour) in zip(axes, series):
        ax.plot([s[key] for s in profile["chimney"]], z, color=colour, lw=2)
        ax.set_xlabel(title, fontsize=9)
        ax.grid(alpha=.3)
    axes[3].axvline(0, color="black", lw=.8)
    axes[0].set_ylabel("height above the chimney base (m)")
    return save(fig, "chimney_profile.png")


def fig_legacy(base: dict, back_pressure: list[dict]) -> str:
    p = an.build(base)
    speeds = list(range(230, 451, 5))
    rows = [(s, solve_steady(p, s, p.t_gas_c, p.t_amb_c)) for s in speeds]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    legacy = [an.legacy_flow(o.p1_pa, o.p2_pa, o.t_gas_c) for _, o in rows]
    axes[0].plot(speeds, legacy, color=MAGENTA, lw=2, label="legacy formula value")
    axes[0].set_xlabel("fan speed (rpm)")
    axes[0].set_ylabel("legacy value (old system units)", color=MAGENTA)
    twin = axes[0].twinx()
    twin.plot(speeds, [o.q_m3_s for _, o in rows], color=BLUE, lw=2)
    twin.set_ylabel("true flow (m³/s)", color=BLUE)
    axes[0].set_title("Fan speed raised: true flow rises all the way", fontsize=10)
    axes[0].grid(alpha=.3)
    axes[1].plot([r["p2"] for r in back_pressure], [r["legacy"] for r in back_pressure], color=MAGENTA, lw=2, marker="o")
    axes[1].set_xlabel(f"P2 level (Pa) at a constant true flow of {an.TARGET_FLOW} m³/s")
    axes[1].set_ylabel("legacy value")
    axes[1].set_title("Same flow, different back-pressure", fontsize=10)
    axes[1].grid(alpha=.3)
    return save(fig, "legacy_value.png")


def fig_loop(base: dict, disturbance, charge) -> str:
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    for (kp, ki), colour in zip(((1.5, 0.05), (1.5, 0.2), (0.5, 0.5)), (BLUE, GREEN, ORANGE)):
        records = an.step_records(base, kp, ki)
        axes[0].plot([r["time_s"] - 300 for r in records], [r["flow_true_m3s"] for r in records], color=colour,
                     lw=2, label=f"Kp {kp}, Ki {ki}")
    axes[0].axhline(STEP_TARGET, color=GREY, ls="--", lw=1)
    axes[0].set_xlim(-10, 200)
    axes[0].set_xlabel(f"seconds after the setpoint step {STEP_START} → {STEP_TARGET} m³/s")
    axes[0].set_ylabel("true flow (m³/s)")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=.3)
    for ax, records, t0, label in ((axes[1], disturbance["records"], 300.0, "seconds after the cold front (30 → 15 °C)"),
                                   (axes[2], charge["records"], charge["records"][0]["time_s"], "seconds (fuel charge every 900 s)")):
        t = [r["time_s"] - t0 for r in records]
        ax.plot(t, [r["flow_true_m3s"] for r in records], color=BLUE, lw=2)
        ax.axhline(an.TARGET_FLOW, color=GREY, ls="--", lw=1)
        ax.set_ylim(an.TARGET_FLOW * 0.9, an.TARGET_FLOW * 1.1)
        ax.set_xlabel(label)
        ax.set_ylabel("true flow (m³/s)", color=BLUE)
        twin = ax.twinx()
        twin.plot(t, [r["rpm_commanded"] for r in records], color=ORANGE, lw=1.5)
        twin.set_ylabel("commanded fan rpm", color=ORANGE)
        ax.grid(alpha=.3)
    axes[1].set_xlim(-5, 150)
    return save(fig, "loop_responses.png")


# --------------------------------------------------------------------------- the report text
def build_report() -> str:
    base = an.defaults()
    p = an.build(base)
    sweep = an.baseline_sweep(base)
    travel = an.tornado(base)
    relative = an.tornado(base, relative=0.10)
    fan_vs_draft = an.fan_effect_vs_draft(base)
    ambients, gas_temps = (10, 20, 30, 40), (90, 110, 130, 160, 200, 250)
    grid = an.rpm_needed_grid(base, ambients, gas_temps)
    envelope = an.envelope_vs_ambient(base, ambients)
    taper = an.chimney_taper_study(base)
    betas = an.plate_beta_study(base, betas=(0.5, 0.6, 0.7, 0.75))
    resolution = an.flow_resolution_vs_flow(base)
    errors = an.estimate_error_table(base)
    back_pressure = an.legacy_value_vs_back_pressure(base)
    back_pressure_valid = [r for r in back_pressure if r["legacy"] is not None]
    readable = an.lowest_readable_speed(base)
    pid_grid = an.pid_tuning_grid(base)
    lags = an.lag_study(base)
    disturbance = an.disturbance_response(base)
    charge = an.charge_disturbance(base)
    windup = an.windup_recovery(base)

    natural = solve_steady(p, 0.0, p.t_gas_c, p.t_amb_c)
    site = solve_steady(p, SITE["rpm"], SITE["t_gas"], p.t_amb_c)
    site_profile = build_profile(p, site, p.t_amb_c)
    calcs = site_profile["calcs"]
    losses = calcs["budget"]["losses"]
    site_legacy = an.legacy_flow(SITE["p1"], SITE["p2"], SITE["t_gas"])
    centre = relative[0]["centre"]
    q_min, q_max = an.flow_at(p, p.motor_min_rpm), an.flow_at(p, p.motor_max_rpm)
    at_max = sweep[-1]
    no_restriction = solve_steady(an.build(base, restriction_free_area_m2=3.0), SITE["rpm"], SITE["t_gas"], p.t_amb_c)

    figs = {
        "flow": fig_flow_vs_rpm(base), "heat": fig_heatmap(ambients, gas_temps, grid),
        "tornado": fig_tornado(relative), "env": fig_envelope(ambients, envelope),
        "press": fig_pressures(base), "chimney": fig_chimney(base),
        "legacy": fig_legacy(base, back_pressure_valid), "loop": fig_loop(base, disturbance, charge),
    }

    fan_adds = [r["fan_adds"] for r in fan_vs_draft]
    weakest = min(fan_vs_draft, key=lambda r: r["draft"])
    strongest = max(fan_vs_draft, key=lambda r: r["draft"])
    grid_values = [v for row in grid for v in row if v is not None]
    cd5 = errors["cd_table"][(5, 28.5)]
    m31 = errors["cd_table"][(0, 31.0)]
    m26 = errors["cd_table"][(0, 26.0)]
    drift = errors["drift"]
    p2_plus5 = drift["p2_offset"][5]
    t_plus30 = drift["t_offset"][30]
    grid_by = {(r["kp"], r["ki"]): r for r in pid_grid}
    holdable = [r for r in resolution if r["holdable"]]
    lag_by = {(r["param"], r["value"]): r for r in lags}
    legacy_readable = [r for r in sweep if r["legacy"] is not None]
    legacy_peak = max(legacy_readable, key=lambda r: r["legacy"])
    top = site_profile["top"]
    by_name = {r["name"]: r for r in relative}

    out = []
    w = out.append

    w(f"""# How the parameters affect each other — kiln process simulation report

Generated {date.today().isoformat()} by `python -m sim.report` from the simulation in `sim/` (natural draft, fan,
orifice plate and tapered chimney, with the real `fan-ctrl` PID in a closed loop). Rerun it after changing the model
or the defaults and the numbers below update.

> **Read this first.** Parameter values are **placeholders**, except the chimney dimensions given by the owner
> (125 ft tall, 5 ft square at the base, 3 ft square at the top) and the values tuned to one site reading (§3).
> Trust the **directions, the relative sizes and the interactions**. Do not quote flows, pressures or rpm as
> predictions for the real kiln. §9 lists what the model leaves out.

## 1. The system being modelled

The orifice plate sits **between the fan and the chimney** (owner, 2026-11-16). Heat reuse inside the kiln is not
modelled.

```
 kiln and flues ──► FAN ──► short duct ──► ORIFICE PLATE ──► restriction ──► chimney ──► outside air
 (resistance, as              (adds          P1 | P2, T        (loss seen     (buoyancy =      (pressure falls
  a free area)                 pressure)                        on site)       natural draft)    with height)
```

Default operating point: exhaust gas {p.t_gas_c:.0f} °C, {p.t_amb_c:.0f} °C outside.
**Natural draft alone moves {natural.q_m3_s:.2f} m³/s** ({natural.draft_pa:.0f} Pa of draft). Between its minimum
({p.motor_min_rpm:.0f} rpm) and maximum ({p.motor_max_rpm:.0f} rpm) speed the fan lets the loop hold
**{q_min:.2f} to {q_max:.2f} m³/s**. The default setpoint of {an.TARGET_FLOW} m³/s needs about **{centre['rpm_needed']:.0f} rpm**.

## 2. How the pieces connect

The model finds the flow from one pressure balance: **flow = √(total push ÷ total resistance)**.

* Push: kiln gauge pressure + natural draft + fan.
* Resistance: kiln and flues, fan-to-plate duct, plate (permanent loss), restriction, chimney friction, chimney exit.

Consequences that explain most of what follows:

1. **The fan and the draft add as pressures, but flow goes as a square root.** The more draft there already is, the
   less extra flow the same fan speed buys (§6.1).
2. **The plate is on the fan's discharge side.** P1 and P2 are negative when draft dominates and positive when the
   fan pushes. The site transmitters read 0–{p.p_range_pa:.0f} Pa only, so they are blind at low fan speed (§4).
3. **The plate signal is ΔP ∝ flow²**, so the resolution gets coarse at low flow (§6.5).
4. **The controller never sees the true flow**, only a value built from P1, P2 and T (§5, §6.6).

## 3. Check against the one real operating point

LabVIEW screen, 17-03-2026: P1 {SITE['p1']} Pa, P2 {SITE['p2']} Pa, exhaust {SITE['t_gas']} °C, fan {SITE['rpm']:.0f} rpm.

{table(["", "site", "model at the same speed and temperature"],
       [["P1 (Pa)", SITE['p1'], f"{site.p1_pa:.1f}"], ["P2 (Pa)", SITE['p2'], f"{site.p2_pa:.1f}"],
        ["Plate ΔP (Pa)", f"{SITE['p1'] - SITE['p2']:.1f}", f"{site.plate_dp_pa:.1f}"],
        ["True flow (m³/s)", "not known", f"{site.q_m3_s:.2f}"]])}

The match was obtained by choosing four placeholder values, so it is a **fit, not a confirmation**: duct and plate
size (to give the measured ΔP at a believable flow), fan curve (about {site.fan_dp_pa:.0f} Pa at 380 rpm, as the
VelKilnMaster cold-start model assumes), kiln free area, and one more that needs explaining.

**The restriction.** A {p.chimney_height_m:.1f} m chimney at {SITE['t_gas']} °C gives about {site.draft_pa:.0f} Pa of
draft. With only the chimney after the plate, P2 would be **{no_restriction.p2_pa:.0f} Pa** (suction). The site shows
**+{SITE['p2']:.0f} Pa**. About {losses['restriction_pa']:.0f} Pa is being lost between the plate and the chimney top,
while the chimney as given accounts for {losses['chimney_friction_pa'] + losses['exit_pa']:.0f} Pa (friction
{losses['chimney_friction_pa']:.1f}, exit {losses['exit_pa']:.1f}). The model carries this as an equivalent opening
of {p.restriction_free_area_m2} m² (`restriction_free_area_m2`). Possible causes, to be checked on site:

1. 3 ft and 5 ft are **outside** dimensions. An inside top of about {math.sqrt(p.restriction_free_area_m2) * FT_PER_M:.1f} ft
   square would lose this much on its own.
2. A damper, bend, long flue or soot between the plate and the chimney.
3. Strong cooling in the chimney, so the real draft is well below {site.draft_pa:.0f} Pa.
4. P2 is tapped somewhere other than just after the plate.

Where the push goes at this point:

{table(["pushing", "Pa", "resisting", "Pa"],
       [["natural draft", f"{site.draft_pa:.0f}", "kiln and flues", f"{losses['kiln_pa']:.0f}"],
        ["fan", f"{site.fan_dp_pa:.0f}", "fan-to-plate duct", f"{losses['fan_to_plate_pa']:.1f}"],
        ["", "", "plate (permanent loss)", f"{losses['plate_pa']:.1f}"],
        ["", "", "restriction", f"{losses['restriction_pa']:.0f}"],
        ["", "", "chimney friction + exit", f"{losses['chimney_friction_pa'] + losses['exit_pa']:.1f}"]])}

Other figures at this point: {calcs['mass_flow_t_h']:.1f} t/h of gas; {calcs['velocity']['duct_m_s']:.1f} m/s in the duct,
{calcs['velocity']['plate_bore_m_s']:.1f} m/s through the plate bore, {calcs['velocity']['chimney_exit_m_s']:.1f} m/s at the chimney exit;
fan air power {calcs['fan_air_power_w'] / 1000:.2f} kW (about {calcs['fan_shaft_power_w'] / 1000:.1f} kW at the shaft with the placeholder
efficiency); the gas carries {calcs['heat_carried_w'] / 1000:.0f} kW above ambient and loses {calcs['heat_lost_chimney_w'] / 1000:.0f} kW
through the chimney wall, leaving at {top['t_c']:.0f} °C. Natural draft supplies {calcs['draft_share'] * 100:.0f} % of the push.

{figs['chimney']}

Outside air pressure at the chimney top is {site_profile['ground']['p_abs_pa'] - top['outside']['p_abs_pa']:.0f} Pa below ground level
({top['outside']['rho']:.3f} against {site_profile['ground']['rho']:.3f} kg/m³). The draft exists because the hot gas inside
({top['rho']:.3f} kg/m³ at the top) is lighter still.

## 4. What the fan does across its range, and what the transmitters can see

{table(["fan rpm", "flow m³/s", "draft Pa", "fan adds Pa", "fan inlet Pa", "P1 Pa", "P2 Pa", "plate ΔP Pa", "readable?", "legacy value"],
       [[f"{r['rpm']:.0f}", f"{r['q']:.2f}", f"{r['draft']:.0f}", f"{r['fan_dp']:.0f}", f"{r['p_fan_in']:.0f}", f"{r['p1']:.0f}",
         f"{r['p2']:.0f}", f"{r['plate_dp']:.1f}", "yes" if r['readable'] else "**no**", num(r['legacy'])] for r in sweep])}

{figs['press']}

* A stopped fan is a small restriction ({sweep[0]['fan_dp']:.0f} Pa), not a blockage: natural draft still moves {sweep[0]['q']:.2f} m³/s.
* **Below about {readable['rpm']:.0f} rpm ({readable['q']:.2f} m³/s) P2 is under suction and a 0–{p.p_range_pa:.0f} Pa transmitter cannot
  read it.** Neither the controller's flow nor the legacy value exists there. In the closed loop, a setpoint in that region
  makes the controller under-read the flow and the fan hunts (covered by a test).
* The placeholder minimum speed ({p.motor_min_rpm:.0f} rpm) is **inside** that unreadable region. The minimum speed, the
  transmitter range and the resonance band ({p.resonance_low_rpm:.0f}–{p.resonance_high_rpm:.0f} rpm) have to be chosen together.
* At {at_max['rpm']:.0f} rpm P1 is {at_max['p1']:.0f} Pa, {at_max['p1_range_use'] * 100:.0f} % of the transmitter range.

{figs['flow']}

## 5. The legacy formula value

`calc_pv` is called unchanged, with the default constants from `fan-ctrl/config.py`, the gauge pressures and the
temperature in kelvin. At the site reading it gives **{site_legacy:.1f}**; the old screen showed an averaged {SITE['screen_value']}.
(With `a2 = 0.6096` in place of `0.6096²` it gives {site_legacy / 0.6096:.1f}. Which constant the old system used is still open.)

The formula uses the **ratio P2/P1 of two gauge pressures**, so it depends on the pressure level at the plate and not only
on the differential:

{table(["restriction free area m²", "fan rpm", "true flow m³/s", "plate ΔP Pa", "P1 Pa", "P2 Pa", "legacy value"],
       [[r['area'], f"{r['rpm']:.0f}", f"{r['q']:.2f}", f"{r['plate_dp']:.1f}", f"{r['p1']:.0f}", f"{r['p2']:.0f}", num(r['legacy'])]
        for r in back_pressure])}

{figs['legacy']}

* **Same flow, different back-pressure, different value** ({num(back_pressure_valid[0]['legacy'])} to {num(back_pressure_valid[-1]['legacy'])} above; "–" means P2 fell below 0 Pa and
  the formula has no answer).
  Soot build-up or a damper after the plate would move the legacy value with no change in flow.
* **In this model the legacy value is not a steady function of flow.** It peaks at {legacy_peak['legacy']:.1f} near
  {legacy_peak['rpm']:.0f} rpm and then **falls** as the fan speeds up, because P2/P1 rises towards 1 when the back-pressure
  grows faster than the differential. A PID on a value that falls when flow rises would drive the wrong way.
* The real system was controlled with this value for years, so one of these must be true: the real back-pressure does not
  grow like the modelled restriction; or the old system fed the formula something other than plain gauge pressures; or the
  plant only ever ran on the rising side. **A speed step test on site (rpm against P1 and P2, five or six speeds) would
  settle this and the restriction question in §3 together.** Until then the simulation shows the legacy value and does
  not control with it.

## 6. How parameters interact

### 6.1 The fan matters less when the draft is strong

Same fan move (0 → {an.REFERENCE_RPM:.0f} rpm) in different weather and chimney heights:

{table(["outside T °C", "chimney m", "draft Pa", "flow, fan stopped m³/s", f"flow at {an.REFERENCE_RPM:.0f} rpm m³/s", "fan adds m³/s"],
       [[r['t_amb'], r['height'], f"{r['draft']:.0f}", f"{r['q_natural']:.2f}", f"{r['q_with_fan']:.2f}", f"{r['fan_adds']:.2f}"] for r in fan_vs_draft])}

The fan adds **{min(fan_adds):.2f}–{max(fan_adds):.2f} m³/s** depending on the draft already there: {weakest['fan_adds']:.2f} m³/s at the
weakest draft ({weakest['draft']:.0f} Pa) and {strongest['fan_adds']:.2f} m³/s at the strongest ({strongest['draft']:.0f} Pa). The fan's
effect on flow, and so the loop gain, changes with weather and exhaust temperature.

### 6.2 Weather × exhaust temperature decide how hard the fan works

Fan rpm needed to hold {an.TARGET_FLOW} m³/s:

{table(["outside T °C ↓ / exhaust gas °C →"] + [str(g) for g in gas_temps],
       [[str(a)] + ["n/a" if v is None else f"{v:.0f}" for v in row] for a, row in zip(ambients, grid)])}

{figs['heat']}

The required speed runs from {min(grid_values):.0f} rpm (cool air, hot gas) to {max(grid_values):.0f} rpm (hot air, cool gas).

### 6.3 There is a minimum flow the loop cannot go below

The fan can add flow but cannot brake it:

{table(["outside T °C", "natural draft alone m³/s", f"lowest holdable (fan at {p.motor_min_rpm:.0f} rpm) m³/s", f"highest holdable (fan at {p.motor_max_rpm:.0f} rpm) m³/s"],
       [[r['t_amb'], f"{r['q_natural']:.2f}", f"{r['q_min']:.2f}", f"{r['q_max']:.2f}"] for r in envelope])}

{figs['env']}

A setpoint below the "lowest holdable" line cannot be reached with the fan alone; holding lower flows would need a damper.

### 6.4 Chimney taper

{table(["top inside side m", "ft", "exit loss Pa", "friction Pa", f"flow at {an.REFERENCE_RPM:.0f} rpm m³/s", "P2 Pa", f"rpm for {an.TARGET_FLOW}"],
       [[r['top_side'], f"{r['top_side'] * FT_PER_M:.1f}", f"{r['loss_exit']:.1f}", f"{r['loss_friction']:.1f}", f"{r['q_fixed_rpm']:.2f}",
         f"{r['p2']:.0f}", rpm(r['rpm_needed'])] for r in taper])}

The exit loss goes as 1/side⁴. At 3 ft the top costs {taper[2]['loss_exit']:.0f} Pa; at {taper[0]['top_side'] * FT_PER_M:.1f} ft it would cost
{taper[0]['loss_exit']:.0f} Pa and raise P2 to {taper[0]['p2']:.0f} Pa. This is why the inside dimension of the top matters (§3, cause 1).

### 6.5 Plate bore, transmitter range and flow resolution

{table(["plate β", f"rpm for {an.TARGET_FLOW}", "plate ΔP Pa", "P1 Pa", "P1 vs range", "ΔP in PLC counts (full scale 6000)", "flow resolution % per count"],
       [[f"{r['beta']:.2f}", rpm(r['rpm_needed']) + (" (> motor max)" if (r['rpm_needed'] or 0) > p.motor_max_rpm else ""),
         f"{r['plate_dp']:.0f}", f"{r['p1']:.0f}", f"{r['p1_range_use'] * 100:.0f} %",
         f"{r['dp_counts']:.0f}", f"{r['pct_per_count']:.3f}"] for r in betas])}

A smaller bore gives a stronger signal but costs fan speed and pushes P1 towards the top of the transmitter range.

{table(["flow m³/s", "plate ΔP Pa", "ΔP counts", "flow resolution % per count", "can the loop hold it?"],
       [[f"{r['q']:.1f}", f"{r['plate_dp']:.1f}", f"{r['dp_counts']:.0f}", f"{r['pct_per_count']:.3f}", "yes" if r['holdable'] else "no (outside the envelope)"] for r in resolution])}

Across the flows the loop can hold, one count is a {holdable[0]['pct_per_count'] / holdable[-1]['pct_per_count']:.1f}× bigger slice of the flow at
{holdable[0]['q']} m³/s than at {holdable[-1]['q']} m³/s. The ΔP is only about {centre['plate_dp_fixed']:.0f} Pa of a {p.p_range_pa:.0f} Pa range, read as the
difference of two transmitters, so each count is about {100.0 / (2 * centre['plate_dp_fixed'] / p.p_range_pa * 6000):.2f} % of flow.

### 6.6 What measurement errors do to the TRUE flow

The controller adjusts the fan until *its estimate* equals the setpoint ({an.TARGET_FLOW} m³/s). True flow in that case:

{table(["assumed Cd error ↓ / assumed gas molar mass →"] + [f"{m} g/mol" for m in errors['molar_masses']],
       [[f"{cd:+d} %"] + [f"{errors['cd_table'][(cd, m)]:.2f}" for m in errors['molar_masses']] for cd in errors['cd_errors']])}

* The true gas is {p.gas_molar_mass_g_mol} g/mol. Assuming 31 gives **{(m31 / an.TARGET_FLOW - 1) * 100:+.1f} %**, assuming 26 gives
  **{(m26 / an.TARGET_FLOW - 1) * 100:+.1f} %**; believing the plate Cd is 5 % higher than it is gives **{(cd5 / an.TARGET_FLOW - 1) * 100:+.1f} %**.
  The controller reports "on setpoint" in every case.

{table(["drift", "P1 reads high by (Pa)", "P2 reads high by (Pa)"],
       [[f"{off:+d}", f"{drift['p1_offset'][off]:.2f}", f"{drift['p2_offset'][off]:.2f}"] for off in (-10, -5, 5, 10)])}

* **A small drift is a large flow error**, because the ΔP is small: P2 reading 5 Pa high gives {p2_plus5:.2f} m³/s
  ({(p2_plus5 / an.TARGET_FLOW - 1) * 100:+.1f} %). The same drift on P1 gives the opposite error; equal drift on both cancels.
* Temperature drift matters least: +30 K gives {(t_plus30 / an.TARGET_FLOW - 1) * 100:+.1f} %.

## 7. Which parameters matter most

Each parameter moved by ±10 % of its own value; output: fan speed needed for {an.TARGET_FLOW} m³/s (centre {centre['rpm_needed']:.0f} rpm).

{table(["Parameter", "−10 % → +10 %", "natural flow m³/s", f"flow at {an.REFERENCE_RPM:.0f} rpm m³/s", f"rpm for {an.TARGET_FLOW}"],
       [[r['label'], f"{value(r['name'], r['lo_value'])} → {value(r['name'], r['hi_value'])}",
         f"{r['lo']['q_natural']:.2f} → {r['hi']['q_natural']:.2f}",
         f"{r['lo']['q_fixed_rpm']:.2f} → {r['hi']['q_fixed_rpm']:.2f}",
         f"{rpm(r['lo']['rpm_needed'])} → {rpm(r['hi']['rpm_needed'])}"] for r in relative])}

{figs['tornado']}

* **The fan curve leads** ({relative[0]['label']}: {swing(relative[0]):.0f} rpm of swing). The real fan curve or nameplate is the
  most valuable missing fact.
* **Gas molar mass** moves the answer by {swing(by_name['gas_molar_mass_g_mol']):.0f} rpm and nobody controls it (wood moisture, firing stage).
* **The two unknown resistances** follow: restriction after the plate ({swing(by_name['restriction_free_area_m2']):.0f} rpm) and kiln free
  area ({swing(by_name['kiln_free_area_m2']):.0f} rpm). The kiln free area changes all day as dampers move.
* Exhaust temperature ±10 % moves it {swing(by_name['t_gas_c']):.0f} rpm; chimney height {swing(by_name['chimney_height_m']):.0f} rpm.
* The chimney's own size barely matters while the restriction dominates: top side {swing(by_name['chimney_top_side_m']):.0f} rpm.

The same sweep by ±10 % of each slider's travel (depends on the slider ranges chosen for the GUI):

{table(["Parameter", "moved to", f"rpm for {an.TARGET_FLOW}"],
       [[r['label'], f"{value(r['name'], r['lo_value'])} → {value(r['name'], r['hi_value'])}",
         f"{rpm(r['lo']['rpm_needed'])} → {rpm(r['hi']['rpm_needed'])}"] for r in travel[:10]])}

## 8. How the control loop behaves

Closed loop with the real `PIDController`, output mapped to {p.pid_min_rpm:.0f}–{p.pid_max_rpm:.0f} rpm. Setpoint step
{STEP_START} → {STEP_TARGET} m³/s, no sensor noise, settled = within 2 %:

{table(["Kp ↓ / Ki →"] + [f"Ki {ki}" for ki in (0.05, 0.2, 0.5)],
       [[f"Kp {kp}"] + [f"settle {secs(grid_by[(kp, ki)]['settle_s'])}, overshoot {grid_by[(kp, ki)]['overshoot_pct']:.1f} %" for ki in (0.05, 0.2, 0.5)] for kp in (0.5, 1.5, 3.0)])}

{figs['loop']}

* Ki sets the speed. The default Kp {p.kp}, Ki {p.ki} settles in {secs(grid_by[(1.5, 0.2)]['settle_s'])} with {grid_by[(1.5, 0.2)]['overshoot_pct']:.1f} % overshoot.
  These gains are a starting point for the PLC's PID (PIDAT), not a copy: its form differs.
* **Cold front** (outside 30 → 15 °C): the true flow deviates at most {disturbance['peak_deviation']:.2f} m³/s
  ({disturbance['peak_deviation'] / an.TARGET_FLOW * 100:.1f} %); the fan settles at {disturbance['rpm_after']:.0f} rpm.
* **Fuel charges** (kiln opened {charge['open_pct']:.0f} % wider for 60 s every 15 minutes): peak flow deviation
  {charge['peak_deviation']:.2f} m³/s ({charge['peak_deviation'] / an.TARGET_FLOW * 100:.1f} %), fan speed moving between {charge['rpm_min']:.0f} and
  {charge['rpm_max']:.0f} rpm. The size of the opening is a guess; stage 2 will supply it from the kiln model.
* **Saturation and windup:** after 10 minutes pinned at minimum speed, recovery takes **{secs(windup['with'])} with anti-windup
  against {secs(windup['without'])} without**. The PLC's PID must have anti-windup.

{table(["parameter", "value s", "settling", "overshoot"],
       [[SPEC_BY_NAME[r['param']].label, r['value'], secs(r['settle_s']), f"{r['overshoot_pct']:.1f} %"] for r in lags])}

* The loop stays stable for every lag tested; the worst cases are gas flow lag {lag_by[('flow_tau_s', 30.0)]['value']:.0f} s
  ({lag_by[('flow_tau_s', 30.0)]['overshoot_pct']:.0f} % overshoot) and motor lag {lag_by[('motor_tau_s', 20.0)]['value']:.0f} s
  ({lag_by[('motor_tau_s', 20.0)]['overshoot_pct']:.0f} %).
* Sensor faults (covered by tests): an open circuit (counts 8000) on any channel drops the fan to the safe speed and the loop
  resumes bumplessly when repaired. A stuck signal, or a transmitter pinned at the bottom of its range, looks healthy.

## 9. What this suggests

1. **Do a speed step test on site**: five or six fan speeds, log rpm, P1, P2 and temperature. It answers the restriction
   question (§3), the legacy value question (§5) and gives a fan-and-system curve.
2. **Confirm the chimney's inside dimensions** and what sits between the plate and the chimney.
3. **Get the fan curve or nameplate** (§7).
4. **Choose the minimum fan speed deliberately**: above the resonance band and above the speed where P2 can be read (§4).
5. **Do not carry the legacy formula forward untested.** Characterise it against logs first (§5).
6. **Zero-check both transmitters regularly**: 5 Pa of drift is a {abs(p2_plus5 / an.TARGET_FLOW - 1) * 100:.0f} % flow error (§6.6).
7. **Make sure the PLC's PID has anti-windup and bumpless start** (§8).

## 10. What the model leaves out

* Placeholder values (see top). The fit in §3 uses one operating point; one point cannot fix four unknowns.
* The restriction stands for an unexplained loss. If the cause is cooling or a different tap position, its behaviour with
  speed will differ from a fixed opening.
* The kiln is one free area and one gas temperature. Dampers, fuel charges and the moving fire are stage 2
  (`project/whole-kiln-simulation-plan.md`).
* Incompressible pressure balance; static pressures only (velocity-head changes between sections ignored except the exit loss).
* Fan heating ignored; a stopped fan is a passive restriction; flow never reverses.
* Gas composition is a single molar mass; no condensation or tar. Reynolds numbers use the viscosity of air.
* The PID is the parallel form in `fan-ctrl/pid.py` with simulation-side anti-windup and bumpless start.
* No PLC, HMI or drive communication delays, heartbeat or fallback table.

## 11. Reproduce

```
.venv\\Scripts\\activate
python -m sim.report          # rewrites this file and the figures in project/simulation-report/
python -m sim.server          # the interactive GUI at http://127.0.0.1:5002
pytest tests/sim              # model, loop and API tests
```
""")
    return "\n".join(out)


def main() -> None:
    text = build_report()
    REPORT_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {REPORT_PATH} and figures in {FIG_DIR}")


if __name__ == "__main__":
    main()
