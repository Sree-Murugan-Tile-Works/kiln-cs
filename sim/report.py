"""
Generate the parameter-interaction report: ``python -m sim.report`` (repo root, venv active).

Writes ``project/simulation-report.md`` and the figures in ``project/simulation-report/``. Every number
in the text comes from ``sim.analysis`` (the same model the GUI runs), so rerunning after a change to
the model or the placeholder defaults keeps the report honest.
"""
import math
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sim import analysis as an
from sim.params import SPEC_BY_NAME, make_params
from sim.plant import solve_steady

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "project" / "simulation-report.md"
FIG_DIR = ROOT / "project" / "simulation-report"
FIG_REL = "simulation-report"

BLUE, ORANGE, GREEN, RED, GREY = "#2a6fdb", "#d2691e", "#1f8a4c", "#c8372d", "#6b7686"


# --------------------------------------------------------------------------- small helpers
def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def rpm(v) -> str:
    return "n/a (beyond 3000)" if v is None else f"{v:.0f}"


def secs(v: float) -> str:
    return "never (within the test)" if math.isinf(v) else f"{v:.0f} s"


def value(name: str, v: float) -> str:
    spec = SPEC_BY_NAME[name]
    text = f"{v:.3g}" if abs(v) < 1000 else f"{v:.0f}"
    return f"{text} {spec.unit}".strip().rstrip("-").strip()


def save(fig, name: str) -> str:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(FIG_DIR / name, dpi=130)
    plt.close(fig)
    return f"![{name}]({FIG_REL}/{name})"


# --------------------------------------------------------------------------- figures
def fig_flow_vs_rpm(base: dict) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    speeds = list(range(0, 1501, 50))
    for ax, name, values, title, legend_title in (
            (axes[0], "t_amb_c", (-5, 15, 35), "Weather: outside air temperature (°C)", "outside T °C"),
            (axes[1], "chimney_height_m", (15, 30, 45), "Chimney height (m)", "chimney m")):
        for v, colour in zip(values, (BLUE, GREEN, ORANGE)):
            p = an.build(base, **{name: v})
            ax.plot(speeds, [an.flow_at(p, s) for s in speeds], color=colour, lw=2, label=f"{v:g}")
        ax.axhline(an.TARGET_FLOW, color=GREY, ls="--", lw=1)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("fan speed (rpm)")
        ax.legend(title=legend_title, fontsize=8)
        ax.grid(alpha=.3)
    axes[0].set_ylabel("true flow through the plate (m³/s)")
    axes[0].text(20, an.TARGET_FLOW + 0.05, "setpoint", color=GREY, fontsize=8)
    return save(fig, "flow_vs_rpm.png")


def fig_heatmap(base: dict, ambients, gas_temps, grid) -> str:
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    data = [[math.nan if v is None else v for v in row] for row in grid]
    image = ax.imshow(data, cmap="YlOrRd", aspect="auto", origin="lower")
    ax.set_xticks(range(len(gas_temps)), [f"{g}" for g in gas_temps])
    ax.set_yticks(range(len(ambients)), [f"{a}" for a in ambients])
    ax.set_xlabel("kiln gas temperature before heat reuse (°C)")
    ax.set_ylabel("outside air temperature (°C)")
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            ax.text(j, i, "n/a" if v is None else f"{v:.0f}", ha="center", va="center", fontsize=8,
                    color="white" if (v or 0) > 800 else "black")
    fig.colorbar(image, label=f"fan rpm needed for {an.TARGET_FLOW} m³/s")
    return save(fig, "rpm_needed_heatmap.png")


def fig_tornado(rows) -> str:
    rows = rows[:12][::-1]
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    centre = rows[0]["centre"]["rpm_needed"]
    for i, r in enumerate(rows):
        lo, hi = r["lo"]["rpm_needed"], r["hi"]["rpm_needed"]
        ax.barh(i, (lo or 3000) - centre, color=BLUE, height=.38, label="−10 %" if i == 0 else None)
        ax.barh(i, (hi or 3000) - centre, color=ORANGE, height=.38, label="+10 %" if i == 0 else None)
    ax.set_yticks(range(len(rows)), [r["label"] for r in rows], fontsize=8)
    ax.axvline(0, color="black", lw=.8)
    ax.set_xlabel(f"change in fan rpm needed for {an.TARGET_FLOW} m³/s (centre {centre:.0f} rpm)")
    ax.legend(title="parameter moved", fontsize=8)
    ax.grid(axis="x", alpha=.3)
    return save(fig, "tornado_relative.png")


def fig_envelope(base: dict, ambients, rows) -> str:
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.fill_between(ambients, [r["q_min"] for r in rows], [r["q_max"] for r in rows], color=BLUE, alpha=.2,
                    label="flow the loop can hold")
    ax.plot(ambients, [r["q_natural"] for r in rows], color=GREEN, ls="--", label="natural draft alone (fan stopped)")
    ax.plot(ambients, [r["q_min"] for r in rows], color=BLUE)
    ax.plot(ambients, [r["q_max"] for r in rows], color=BLUE)
    ax.axhline(an.TARGET_FLOW, color=GREY, ls="--", lw=1)
    ax.text(ambients[0], an.TARGET_FLOW + .05, "setpoint", color=GREY, fontsize=8)
    ax.set_xlabel("outside air temperature (°C)")
    ax.set_ylabel("flow (m³/s)")
    ax.legend(fontsize=8, loc="center right")
    ax.grid(alpha=.3)
    return save(fig, "operating_envelope.png")


def fig_pressures(base: dict, sweep) -> str:
    p = an.build(base)
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    speeds = [r["rpm"] for r in sweep]
    ax.plot(speeds, [r["p1"] for r in sweep], color=BLUE, marker="o", label="P1 (upstream of plate)")
    ax.plot(speeds, [r["p2"] for r in sweep], color=RED, marker="o", label="P2 (downstream of plate)")
    ax.axhline(-p.p_range_pa, color=RED, ls="--", lw=1)
    ax.text(speeds[0], -p.p_range_pa + 12, "transmitter range limit", color=RED, fontsize=8)
    ax.set_xlabel("fan speed (rpm)")
    ax.set_ylabel("gauge pressure (Pa)")
    ax.legend(fontsize=8)
    ax.grid(alpha=.3)
    return save(fig, "pressures_vs_rpm.png")


def fig_loop(base: dict, disturbance) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    for (kp, ki), colour in zip(((1.5, 0.05), (1.5, 0.2), (1.5, 0.5)), (BLUE, GREEN, ORANGE)):
        records = an.step_records(base, kp, ki)
        axes[0].plot([r["time_s"] - 300 for r in records], [r["flow_true_m3s"] for r in records], color=colour,
                     lw=2, label=f"Kp {kp}, Ki {ki}")
    axes[0].axhline(5.0, color=GREY, ls="--", lw=1)
    axes[0].set_xlim(-10, 150)
    axes[0].set_xlabel("seconds after the setpoint step 4.0 → 5.0 m³/s")
    axes[0].set_ylabel("true flow (m³/s)")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=.3)
    recs = disturbance["records"]
    t = [r["time_s"] - 300 for r in recs]
    axes[1].plot(t, [r["flow_true_m3s"] for r in recs], color=BLUE, lw=2, label="true flow")
    axes[1].axhline(an.TARGET_FLOW, color=GREY, ls="--", lw=1)
    axes[1].set_xlim(-5, 100)
    axes[1].set_ylim(an.TARGET_FLOW * 0.9, an.TARGET_FLOW * 1.1)      # ±10 % window: shows the true size of the blip
    axes[1].set_xlabel("seconds after the cold front (25 → 5 °C)")
    axes[1].set_ylabel("flow (m³/s)", color=BLUE)
    twin = axes[1].twinx()
    twin.plot(t, [r["rpm_commanded"] for r in recs], color=ORANGE, lw=2)
    twin.set_ylabel("commanded fan rpm", color=ORANGE)
    axes[1].grid(alpha=.3)
    return save(fig, "loop_responses.png")


# --------------------------------------------------------------------------- the report text
def build_report() -> str:
    base = an.defaults()
    p = an.build(base)
    sweep = an.baseline_sweep(base)
    travel = an.tornado(base)
    relative = an.tornado(base, relative=0.10)
    fan_vs_draft = an.fan_effect_vs_draft(base)
    ambients, gas_temps = (-10, 0, 10, 20, 30, 40), (150, 200, 250, 300, 350, 400)
    grid = an.rpm_needed_grid(base, ambients, gas_temps)
    envelope = an.envelope_vs_ambient(base, ambients)
    reuse = an.reuse_interaction(base)
    betas = an.plate_beta_study(base)
    resolution = an.flow_resolution_vs_flow(base)
    errors = an.estimate_error_table(base)
    pid_grid = an.pid_tuning_grid(base)
    lags = an.lag_study(base)
    disturbance = an.disturbance_response(base)
    windup = an.windup_recovery(base)

    natural = solve_steady(p, 0.0, p.t_gas_c, p.t_amb_c)
    centre = relative[0]["centre"]
    q_min, q_max = an.flow_at(p, p.motor_min_rpm), an.flow_at(p, p.motor_max_rpm)
    at_max = sweep[-1]
    figs = {
        "flow": fig_flow_vs_rpm(base), "heat": fig_heatmap(base, ambients, gas_temps, grid),
        "tornado": fig_tornado(relative), "env": fig_envelope(base, ambients, envelope),
        "press": fig_pressures(base, sweep), "loop": fig_loop(base, disturbance),
    }

    fan_adds = [r["fan_adds"] for r in fan_vs_draft]
    weakest = min(fan_vs_draft, key=lambda r: r["draft"])
    strongest = max(fan_vs_draft, key=lambda r: r["draft"])
    grid_values = [v for row in grid for v in row if v is not None]
    cd5 = errors["cd_table"][(5, 28.5)]
    m31 = errors["cd_table"][(0, 31.0)]
    m26 = errors["cd_table"][(0, 26.0)]
    drift = errors["drift"]
    p2_plus10 = drift["p2_offset"][10]
    t_plus30 = drift["t_offset"][30]
    default_grid = {(r["kp"], r["ki"]): r for r in pid_grid}
    reuse_by = {(r["extraction"], r["k_reuse"]): r for r in reuse}
    holdable = [r for r in resolution if r["holdable"]]
    lag_by = {(r["param"], r["value"]): r for r in lags}

    top_relative = relative[:5]
    out = []
    w = out.append

    w(f"""# How the parameters affect each other — kiln process simulation report

Generated {date.today().isoformat()} by `python -m sim.report` from the simulation in `sim/` (model of natural draft,
chimney, orifice plate and fan, with the real `fan-ctrl` PID in a closed loop). Rerun it after changing the model or
the defaults and the numbers below update.

> **Read this first.** Every parameter value is a **placeholder** ("generally meaningful"), not site data. Trust the
> **directions, the relative sizes and the interactions**; do not quote the absolute numbers (flows, pressures, rpm) as
> predictions for the real kiln. §8 lists what the model leaves out.

## 1. The system being modelled

The heat reuse happens **inside the kiln's own tunnels, before the plate** (owner correction, 2026-11-14), so the plate
and the fan see gas that has already been cooled:

```
 kiln firing zone ─► heat-reuse tunnels ─► duct ─► ORIFICE PLATE ─► fan ─► chimney ─► outside air
 (T_kiln)            (gas cooled, loss       (loss)   P1 | P2, T        (adds     (buoyancy =
                      shows up in P1)                                    pressure)  natural draft)
```

Default operating point (all sliders at their defaults): kiln gas {p.t_gas_c:.0f} °C leaving the firing zone, {p.t_amb_c:.0f} °C outside,
{p.reuse_extraction * 100:.0f} % of the heat taken out by the tunnels so the plate sees {natural.t_plate_c:.0f} °C.
**Natural draft alone moves {natural.q_m3_s:.2f} m³/s** ({natural.draft_pa:.0f} Pa of draft). The fan, between its minimum
({p.motor_min_rpm:.0f} rpm) and maximum ({p.motor_max_rpm:.0f} rpm) speed, lets the loop hold anything from
**{q_min:.2f} to {q_max:.2f} m³/s**. The default setpoint of {an.TARGET_FLOW} m³/s needs about **{centre['rpm_needed']:.0f} rpm**.

## 2. How the pieces connect

```
 outside T ─────────────────────────────┐
 kiln T ─► reuse extraction ─► T at plate ─► chimney mean T ─► DRAFT ──────┐
 chimney height / diameter / wall loss ──┘        ▲                       │
                                                  │ (more flow = less      ▼
 gas molar mass ─► gas density ─────────────► cooling in chimney)   TOTAL PUSH = draft + fan gain ──► FLOW
                                                                          ▲                          │
 fan rpm ─► fan gain (∝ rpm², fan curve) ────────────────────────────────┘                          ▼
                                                                                           plate ΔP ∝ flow²
 resistances: reuse tunnels, duct, plate (permanent loss), chimney, idle fan ─► divide the push           │
                                                                                         P1, P2 ─► counts ─► controller's flow estimate
 plate Cd / assumed Cd, assumed gas molar mass ───────────────────────────────────────────────────────────► (can be wrong) ─► PID ─► rpm
```

The model finds the flow from one pressure balance: **flow = √(total push ÷ total resistance)**. Four consequences
explain almost everything below:

1. **The fan and the draft add as pressures, but flow goes as a square root.** The more draft there already is, the less
   extra flow the same fan speed buys (§5.1).
2. **Resistance goes as 1/diameter⁴**, so the duct diameter and the plate bore dominate (§4).
3. **The plate signal is ΔP ∝ flow²**, so the instrument sees less at low flow and the resolution gets coarse (§5.5).
4. **The controller never sees the true flow**, only an estimate built from P1, P2, T and *assumed* Cd and gas molar mass.
   Whatever those assumptions get wrong becomes a true-flow error (§5.6).

| Parameter group | Changes the draft | Changes the resistance | Changes the fan's push | Changes what the controller sees | Changes timing |
|---|---|---|---|---|---|
| Weather (outside T, pressure) | ✔ (density difference) | – | – | – | – |
| Kiln gas T, reuse extraction | ✔ (gas lightness) | – | – | ✔ (T at the plate) | slow thermal lag |
| Gas molar mass, specific heat | ✔ | – | ✔ (density) | ✔ (density in the flow equation) | – |
| Reuse tunnel loss, duct, plate β | – | ✔ | – | ✔ (P1/P2 levels, ΔP signal) | – |
| Chimney height/diameter/friction/wall loss | ✔ | ✔ | – | – | – |
| Fan curve (shut-off ΔP, free-delivery flow, rated rpm) | – | ✔ (idle fan) | ✔ | – | – |
| Transmitter range, noise, lag, drift | – | – | – | ✔ | ✔ |
| PID gains, scan, ranges, anti-windup | – | – | ✔ (what rpm is asked for) | – | ✔ |

## 3. Baseline: what the fan does across its range

{table(["fan rpm", "flow m³/s", "draft Pa", "fan adds Pa", "plate ΔP Pa", "P1 Pa", "P2 Pa", "P2 vs ±range"],
       [[f"{r['rpm']:.0f}", f"{r['q']:.2f}", f"{r['draft']:.0f}", f"{r['fan_dp']:.0f}", f"{r['plate_dp']:.0f}",
         f"{r['p1']:.0f}", f"{r['p2']:.0f}", f"{r['p2_range_use'] * 100:.0f} %"] for r in sweep])}

{figs['press']}

* Flow rises from {sweep[0]['q']:.2f} to {sweep[-1]['q']:.2f} m³/s over the fan's range, but **not in proportion to rpm** —
  the draft is a fixed head start (it barely moves: {sweep[0]['draft']:.0f} → {sweep[-1]['draft']:.0f} Pa, only because the faster gas
  cools less in the chimney).
* A stopped fan is a small restriction ({sweep[0]['fan_dp']:.0f} Pa), not a blockage, so natural draft still flows.
* **At {at_max['rpm']:.0f} rpm the downstream pressure P2 is {at_max['p2']:.0f} Pa, {at_max['p2_range_use'] * 100:.0f} % of the placeholder
  ±{p.p_range_pa:.0f} Pa transmitter range**: the P2 transmitter would saturate at the fan's top speed. The transmitter range,
  the plate β and the fan size have to be chosen together (§5.5).

{figs['flow']}

## 4. Which parameters matter most

Two views, because "which matters" depends on how you compare. The **relative** view moves each parameter by ±10 % of its
*own value* (physics only); the **slider-travel** view moves each slider by ±10 % of its *range* (what you feel when
dragging in the GUI). Output shown: the fan speed needed to hold {an.TARGET_FLOW} m³/s (centre: {centre['rpm_needed']:.0f} rpm), plus the
natural-draft-only flow and the flow at a fixed {an.REFERENCE_RPM:.0f} rpm.

**±10 % of each parameter's own value**

{table(["Parameter", "−10 % → +10 %", "natural flow m³/s", f"flow at {an.REFERENCE_RPM:.0f} rpm m³/s", f"rpm for {an.TARGET_FLOW}"],
       [[r['label'], f"{value(r['name'], r['lo_value'])} → {value(r['name'], r['hi_value'])}",
         f"{r['lo']['q_natural']:.2f} → {r['hi']['q_natural']:.2f}",
         f"{r['lo']['q_fixed_rpm']:.2f} → {r['hi']['q_fixed_rpm']:.2f}",
         f"{rpm(r['lo']['rpm_needed'])} → {rpm(r['hi']['rpm_needed'])}"] for r in relative])}

{figs['tornado']}

**±10 % of each slider's travel** (depends on the slider ranges, which are my choice)

{table(["Parameter", "moved to", "natural flow m³/s", f"flow at {an.REFERENCE_RPM:.0f} rpm m³/s", f"rpm for {an.TARGET_FLOW}"],
       [[r['label'], f"{value(r['name'], r['lo_value'])} → {value(r['name'], r['hi_value'])}",
         f"{r['lo']['q_natural']:.2f} → {r['hi']['q_natural']:.2f}",
         f"{r['lo']['q_fixed_rpm']:.2f} → {r['hi']['q_fixed_rpm']:.2f}",
         f"{rpm(r['lo']['rpm_needed'])} → {rpm(r['hi']['rpm_needed'])}"] for r in travel])}

What stands out (relative view):

* **Geometry dominates.** {top_relative[0]['label']} and {top_relative[1]['label']} are the top two: a 10 % change moves the rpm
  needed by roughly {abs(top_relative[0]['hi']['rpm_needed'] - top_relative[0]['lo']['rpm_needed']):.0f} rpm. That is the 1/diameter⁴ effect.
  They are fixed by the installation, but they are also the parameters you can check on site with a tape measure.
* **Gas molar mass is the biggest thing nobody controls.** It moves the rpm needed by
  {abs(next(r for r in relative if r['name'] == 'gas_molar_mass_g_mol')['hi']['rpm_needed'] - next(r for r in relative if r['name'] == 'gas_molar_mass_g_mol')['lo']['rpm_needed']):.0f} rpm for ±10 % (wood moisture and
  firing stage change the flue-gas composition), through both the draft (density) and the controller's estimate.
* **Temperatures matter less than intuition says:** ±10 % of kiln temperature (±{p.t_gas_c * .1:.0f} K) and ±10 % of ambient (±{p.t_amb_c * .1:.1f} K)
  move the rpm needed by {abs(next(r for r in relative if r['name'] == 't_gas_c')['hi']['rpm_needed'] - next(r for r in relative if r['name'] == 't_gas_c')['lo']['rpm_needed']):.0f}
  and {abs(next(r for r in relative if r['name'] == 't_amb_c')['hi']['rpm_needed'] - next(r for r in relative if r['name'] == 't_amb_c')['lo']['rpm_needed']):.0f} rpm. Weather is a small disturbance here (but see §5.2 for big swings).
* **Almost no effect:** atmospheric pressure, kiln gauge pressure, gas specific heat and chimney friction/wall loss
  (within ±10 %). Atmospheric pressure and kiln gauge pressure only shift P1/P2 levels; the flow does not change.

## 5. How parameters interact

### 5.1 The fan matters less when the draft is strong

Same fan move (0 → {an.REFERENCE_RPM:.0f} rpm) in different weather and chimney heights:

{table(["outside T °C", "chimney m", "draft Pa", "flow, fan stopped m³/s", f"flow at {an.REFERENCE_RPM:.0f} rpm m³/s", "fan adds m³/s"],
       [[r['t_amb'], r['height'], f"{r['draft']:.0f}", f"{r['q_natural']:.2f}", f"{r['q_with_fan']:.2f}", f"{r['fan_adds']:.2f}"] for r in fan_vs_draft])}

The fan adds **{min(fan_adds):.2f}–{max(fan_adds):.2f} m³/s** depending on the draft already there: {weakest['fan_adds']:.2f} m³/s at the weakest draft
({weakest['draft']:.0f} Pa) but only {strongest['fan_adds']:.2f} m³/s at the strongest ({strongest['draft']:.0f} Pa). Reason: flow ∝ √(draft + fan push), so each extra pascal of
fan push buys less flow when the total is already large. **The loop gain of the fan therefore changes with the weather and
the kiln temperature** — a fixed tuning is a compromise (it does cope here, §6).

### 5.2 Weather × kiln temperature decide how hard the fan works

Fan rpm needed to hold {an.TARGET_FLOW} m³/s:

{table(["outside T °C ↓ / kiln gas °C →"] + [str(g) for g in gas_temps],
       [[str(a)] + ["n/a" if v is None else f"{v:.0f}" for v in row] for a, row in zip(ambients, grid)])}

{figs['heat']}

The required speed runs from {min(grid_values):.0f} rpm (cold air, hot kiln) to {max(grid_values):.0f} rpm (warm air, cool kiln). In the
corner with cold air and a very hot kiln the draft alone exceeds the setpoint and the fan can stop (0 rpm); if `motor_min_rpm` > 0 the fan
would run anyway and the flow would sit above the setpoint. Kiln temperature moves the answer more than weather does across these ranges
(a 250 K kiln swing against a 50 K weather swing), but both matter.

### 5.3 There is a minimum flow the loop cannot go below

The fan can add flow but cannot brake it. The lowest flow the loop can hold is what natural draft gives at the fan's
minimum speed, and it rises in cold weather:

{table(["outside T °C", "natural draft alone m³/s", f"lowest holdable (fan at {p.motor_min_rpm:.0f} rpm) m³/s", f"highest holdable (fan at {p.motor_max_rpm:.0f} rpm) m³/s"],
       [[r['t_amb'], f"{r['q_natural']:.2f}", f"{r['q_min']:.2f}", f"{r['q_max']:.2f}"] for r in envelope])}

{figs['env']}

A setpoint below the "lowest holdable" line is simply unreachable with the fan alone: the PID pins the fan at minimum and the
flow stays above the setpoint (you can see this in the GUI by raising chimney height and lowering outside temperature). Holding lower flows would need a
damper. The envelope also tells you which setpoints are realistic in each season.

### 5.4 Heat reuse (inside the kiln) interacts with the draft, the pressures and the measurement

Two separate effects of the reuse tunnels, plotted as extraction (how much heat is taken) × tunnel loss (how much they resist):

{table(["heat extracted", "tunnel loss K", "T at plate °C", "natural flow m³/s", f"flow at {an.REFERENCE_RPM:.0f} rpm", "P1 Pa", "plate ΔP Pa", f"rpm for {an.TARGET_FLOW}"],
       [[f"{r['extraction'] * 100:.0f} %", r['k_reuse'], f"{r['t_plate']:.0f}", f"{r['q_natural']:.2f}", f"{r['q_fixed_rpm']:.2f}",
         f"{r['p1']:.0f}", f"{r['plate_dp']:.0f}", rpm(r['rpm_needed'])] for r in reuse])}

* **Extraction cools the gas** → the buoyancy advantage over the outside air shrinks → less draft. {int(reuse_by[(0.0, 3)]['extraction'] * 100)} % → {int(reuse_by[(0.4, 3)]['extraction'] * 100)} % extraction (tunnel loss 3) moves the natural flow
  {reuse_by[(0.0, 3)]['q_natural']:.2f} → {reuse_by[(0.4, 3)]['q_natural']:.2f} m³/s and the rpm needed {rpm(reuse_by[(0.0, 3)]['rpm_needed'])} → {rpm(reuse_by[(0.4, 3)]['rpm_needed'])}.
* **Tunnel loss is pure resistance** → less flow for the same push, and because it sits *before* the plate it deepens the suction at
  **P1 and P2 together** ({reuse_by[(0.2, 0)]['p1']:.0f} → {reuse_by[(0.2, 9)]['p1']:.0f} Pa at P1) while the plate ΔP only changes through the lower flow.
* The two **compound**: the worst corner (40 % extraction, loss 9) needs {rpm(reuse_by[(0.4, 9)]['rpm_needed'])} rpm against {rpm(reuse_by[(0.0, 0)]['rpm_needed'])} rpm for no reuse.
* Practical consequence: **anything that changes the reuse (a damper, a different stage in use, fouling of the tunnels) changes
  the flow and the P1/P2 levels at the same fan speed, even though nothing changed at the plate.** The PID has to absorb it, and a
  sudden P1/P2 shift with no change in ΔP is a clue that the cause is upstream.

### 5.5 Plate bore, transmitter range and flow resolution

A smaller bore (lower β) gives a stronger plate signal but costs fan work and pushes the pressures out of the transmitter range:

{table(["plate β", f"rpm for {an.TARGET_FLOW}", "plate ΔP Pa", "P2 Pa", "P2 vs ±range", "ΔP expressed in PLC counts (full scale 6000)", "flow resolution % per count"],
       [[f"{r['beta']:.2f}", rpm(r['rpm_needed']) + (" (> motor max)" if (r['rpm_needed'] or 0) > p.motor_max_rpm else ""),
         f"{r['plate_dp']:.0f}", f"{r['p2']:.0f}", f"{r['p2_range_use'] * 100:.0f} %",
         f"{r['dp_counts']:.0f}", f"{r['pct_per_count']:.3f}"] for r in betas])}

* β is a three-way trade: **signal strength** (resolution per count), **fan work** (rpm needed), and **transmitter headroom**
  (P2 versus the range). At β = {betas[0]['beta']:.1f} the signal is huge but the fan cannot reach the setpoint and P2 is {betas[0]['p2_range_use'] * 100:.0f} % of the range; at
  β = {betas[-1]['beta']:.1f} the fan hardly works but each PLC count is {betas[-1]['pct_per_count'] / betas[2]['pct_per_count']:.1f}× coarser than at β = {betas[2]['beta']:.1f}.

The square-root law also makes the resolution depend on the flow itself (default plate and range):

{table(["flow m³/s", "plate ΔP Pa", "ΔP counts", "flow resolution % per count", "can the loop hold it?"],
       [[f"{r['q']:.1f}", f"{r['plate_dp']:.0f}", f"{r['dp_counts']:.0f}", f"{r['pct_per_count']:.3f}", "yes" if r['holdable'] else "no (outside the envelope)"] for r in resolution])}

Across the flows the loop can actually hold, one count is a {holdable[0]['pct_per_count'] / holdable[-1]['pct_per_count']:.1f}× bigger slice of the flow at {holdable[0]['q']} m³/s than at
{holdable[-1]['q']} m³/s ({holdable[0]['pct_per_count']:.3f} % against {holdable[-1]['pct_per_count']:.3f} % per count). With the placeholder range that is fine; on the real transmitters a range
chosen for the top of the fan's range may leave too little resolution at the low end.

### 5.6 What measurement errors do to the TRUE flow

The controller adjusts the fan until *its estimate* equals the setpoint ({an.TARGET_FLOW} m³/s). If the estimate is wrong the true flow ends up elsewhere.

True flow when the controller thinks it holds {an.TARGET_FLOW} m³/s:

{table(["assumed Cd error ↓ / assumed gas molar mass →"] + [f"{m} g/mol" for m in errors['molar_masses']],
       [[f"{cd:+d} %"] + [f"{errors['cd_table'][(cd, m)]:.2f}" for m in errors['molar_masses']] for cd in errors['cd_errors']])}

* The true gas is {p.gas_molar_mass_g_mol} g/mol. Assuming it is heavier than it is (31) makes the true flow **{(m31 / an.TARGET_FLOW - 1) * 100:+.1f} %**; lighter (26) gives
  **{(m26 / an.TARGET_FLOW - 1) * 100:+.1f} %**. Believing the plate Cd is 5 % higher than it is gives **{(cd5 / an.TARGET_FLOW - 1) * 100:+.1f} %**. These errors are *invisible to the controller*:
  it always reports "on setpoint".

Transmitter drift (offset added to one reading), true flow when the controller holds {an.TARGET_FLOW}:

{table(["drift (Pa or °C)", "P1 reads high by", "P2 reads high by", "temperature reads high by"],
       [[f"{off:+d}"] + [f"{drift[name][off]:.2f}" for name in ("p1_offset", "p2_offset", "t_offset")] for off in (-30, -10, 10, 30)])}

* **P1 and P2 drift in opposite senses**, because only their difference counts: P2 reading 10 Pa high gives {p2_plus10:.2f} m³/s
  ({(p2_plus10 / an.TARGET_FLOW - 1) * 100:+.1f} %); the same drift on P1 gives the opposite error. A common-mode drift of both cancels. With a ΔP of ~{centre['plate_dp_fixed']:.0f} Pa at this flow,
  a 10 Pa error is a ~{10 / centre['plate_dp_fixed'] * 50:.0f} % flow error (half the ΔP error, from the square root).
* **Temperature drift matters least**: +30 K → {(t_plus30 / an.TARGET_FLOW - 1) * 100:+.1f} % flow (only the gas density in the flow equation depends on it).

## 6. How the control loop behaves

Closed loop with the real `PIDController` (parallel form: `kp·e + ki·∫e + kd·de/dt`, output 0–100 % of the PID speed range).
Setpoint step {4.0} → {5.0} m³/s, no sensor noise, settling = within 2 % of the final value:

{table(["Kp ↓ / Ki →"] + [f"Ki {ki}" for ki in (0.05, 0.2, 0.5)],
       [[f"Kp {kp}"] + [f"settle {secs(default_grid[(kp, ki)]['settle_s'])}, overshoot {default_grid[(kp, ki)]['overshoot_pct']:.1f} %" for ki in (0.05, 0.2, 0.5)] for kp in (0.5, 1.5, 3.0)])}

{figs['loop']}

* **At low and moderate Ki, Ki sets the speed and more Kp makes the final approach slower, not faster.** With this fast plant (gas lag a few seconds) the
  proportional term does most of the job at once and the integral finishes it; the effective integral speed is about Ki ÷ (1 + Kp·plant gain),
  so at Ki 0.05 settling goes {secs(default_grid[(0.5, 0.05)]['settle_s'])} → {secs(default_grid[(1.5, 0.05)]['settle_s'])} → {secs(default_grid[(3.0, 0.05)]['settle_s'])} as Kp rises 0.5 → 1.5 → 3. At high Ki (0.5) the loop
  rings and more Kp damps it instead: overshoot {default_grid[(0.5, 0.5)]['overshoot_pct']:.0f} % → {default_grid[(1.5, 0.5)]['overshoot_pct']:.0f} %. This is a property of the
  parallel form used here; the PLC's PID (PIDAT, 2-DOF with a proportional band) will not behave identically, so any tuning found here is a starting
  point for the PLC, not a copy (open item in `TODO.md`).
* The default Kp {p.kp}, Ki {p.ki} settles in {secs(default_grid[(1.5, 0.2)]['settle_s'])} with {default_grid[(1.5, 0.2)]['overshoot_pct']:.1f} % overshoot: deliberately conservative.
  Ki 0.5 is faster ({secs(default_grid[(1.5, 0.5)]['settle_s'])}) but overshoots {default_grid[(1.5, 0.5)]['overshoot_pct']:.0f} %.

How the **time constants** of the plant, motor, sensors and scan limit the loop (default gains):

{table(["parameter", "value s", "settling", "overshoot"],
       [[SPEC_BY_NAME[r['param']].label, r['value'], secs(r['settle_s']), f"{r['overshoot_pct']:.1f} %"] for r in lags])}

* The loop stays stable in every case tested, and the scan interval (0.5–5 s) hardly matters. A moderate lag even makes the conservative default
  settle sooner (the controller over-drives a little), which is not a free improvement: overshoot appears once a lag reaches tens of seconds:
  gas flow lag {lag_by[('flow_tau_s', 30.0)]['value']:.0f} s → {lag_by[('flow_tau_s', 30.0)]['overshoot_pct']:.0f} % overshoot and {secs(lag_by[('flow_tau_s', 30.0)]['settle_s'])} settling;
  motor/fan lag {lag_by[('motor_tau_s', 20.0)]['value']:.0f} s → {lag_by[('motor_tau_s', 20.0)]['overshoot_pct']:.0f} % overshoot; sensor lag {lag_by[('sensor_tau_s', 10.0)]['value']:.0f} s → {lag_by[('sensor_tau_s', 10.0)]['overshoot_pct']:.0f} %.
  A large fan on a big inertia, or impulse lines choked with tar (slow sensors), are the realistic ways to get there.
* **Weather disturbance:** a cold front (outside 25 → 5 °C) lifts the natural flow to {disturbance['natural_after']:.2f} m³/s; the loop moves the fan to {disturbance['rpm_after']:.0f} rpm. The true flow
  deviates at most {disturbance['peak_deviation']:.2f} m³/s ({disturbance['peak_deviation'] / an.TARGET_FLOW * 100:.1f} %) and is back within 2 % after {secs(disturbance['recovery_s'])}.
  With these placeholder numbers feed-forward on ambient temperature would add little (§7).
* **Saturation and windup:** after 10 minutes with the setpoint below what the fan can reach (fan pinned at minimum), the time to get back to a reachable setpoint is
  **{secs(windup['with'])} with anti-windup versus {secs(windup['without'])} without**. The real `PIDController` has no anti-windup of its own (the simulation adds it around it); the PLC's PID must have it, or the
  loop will sit wound-up for many minutes after a long saturation (cold nights, hot kiln, a closed damper).
* **Sensor faults** (covered by tests, not by a table): an open circuit (counts 8000) on P1, P2 or T drops the fan to the safe speed at once and the loop resumes bumplessly
  when repaired. A *stuck* signal looks healthy to the controller and is not detected — the flow error then grows with the real process.

## 7. What this suggests

1. **Measure these first on site** (largest effect on the answer, §4): duct diameter and plate bore (a tape measure), gas composition / molar mass (flue-gas analysis over a
   firing cycle), plate Cd (calibration or a reference measurement), gas temperature at the plate, chimney height.
2. **Check the transmitter range against the fan's top speed.** The placeholder shows P2 at {at_max['p2_range_use'] * 100:.0f} % of range at maximum rpm. Choose range, β and fan size together (§5.5).
3. **Decide the minimum fan speed deliberately.** It sets the lowest flow you can hold (§5.3). If the process needs lower flows in cold weather, plan a damper.
4. **Feed-forward on ambient temperature looks low priority** if the real plant resembles this model: the PID absorbs a {disturbance['peak_deviation'] / an.TARGET_FLOW * 100:.0f} % transient and recovers in seconds. Revisit once real data exists.
5. **Make sure the PLC's PID has anti-windup and bumpless start** (§6). Without them a long saturation costs many minutes.
6. **Expect the same setting to behave differently in summer and winter** (the fan's loop gain changes by tens of percent with the draft, §5.1); tune at the awkward end.
7. **A drifting P1 or P2 is a flow error you cannot see**; a ΔP-based cross-check or periodic zero check on both transmitters is worth having (§5.6).

## 8. What the model leaves out

* All values are placeholders (§ top). Flows, pressures and rpm are illustrative.
* Incompressible pressure balance (plate ΔP is ~{centre['plate_dp_fixed'] / p.p_atm_pa * 100:.2f} % of atmospheric); hydrostatic effects in horizontal ducts ignored.
* Heat reuse is a fixed extraction fraction and a fixed loss; in reality they depend on the stages in use and on fouling. Gas temperature at the plate follows the kiln with a first-order lag.
* A stopped fan is a passive restriction (no windmilling); flow never reverses (it stalls at zero).
* Gas composition is a single molar mass; no condensation, tar fouling, or moisture in the plate calculation.
* The controller's flow estimate is a clean orifice equation, **not** the legacy empirical `calc_pv` (its input units are unverified and its constants must not be touched).
* The PID is the textbook parallel form in `fan-ctrl/pid.py` with sim-side anti-windup and bumpless start; the PLC's PIDAT may differ.
* No PLC/HMI/drive communication delays, no heartbeat or fallback-table behaviour (planned in `TODO.md`).
* One kiln, one fan, one chimney, no interaction between several kilns or dampers.

## 9. Reproduce

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
