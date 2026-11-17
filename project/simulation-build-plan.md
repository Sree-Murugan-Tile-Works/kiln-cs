# Simulation build plan (stages and commits)

**Status:** written 2026-11-17. Owner asked for a multi-stage build with a commit after each stage.
**Stages A to E (stage 1) are built and committed. Stages F to J (stage 2, the whole kiln) are not
started.** This file fixes the order of work and the design decisions so the build can resume at
any stage.
**Scope:** `sim/`, `tests/sim/` and documents only. Dev machine only. No change to `fan-ctrl/`,
`dashboard/` or hardware. The legacy `calc_pv` formula is called, never changed.

Designs being built: `project/simulation-upgrade-plan.md` (stage 1) and
`project/whole-kiln-simulation-plan.md` (stage 2). Where this file differs from them, this file is
newer.

---

## 1. Rule for every stage

1. Code and tests on the dev machine.
2. `pytest` passes from the project root and changed files compile.
3. `TODO.md` and `Claude_log.md` updated.
4. One commit per stage, so every commit leaves the simulation runnable.

---

## 2. Stages

| Stage | Content | Main files | Done when |
|---|---|---|---|
| A | New physics: layout kiln -> fan -> plate -> chimney, heat reuse removed, tapered square chimney in slices, air pressure falling with height, pressure walk. Loop, analysis and GUI adapted only enough to keep running | `sim/gas.py`, `params.py`, `plant.py`, `loop.py`, `analysis.py`, `report.py`, `tests/sim/*` | Tests pass; GUI still opens |
| B | Site realism: one-sided 0-250 Pa transmitters, fan near 380 rpm, resonance band, legacy `calc_pv` shown beside the true flow, charge and damper disturbances, defaults tuned to the real operating point | `sim/instruments.py`, `loop.py`, `params.py`, `analysis.py` | Default case lands near P1 119 Pa, P2 87 Pa at 380 rpm and 130 degC |
| C | Calculations and data path: velocities, Reynolds numbers, pressure budget, fan power, heat carried and lost; `profile` in `/api/state` | `sim/plant.py`, `server.py` | Hand-calculation tests pass |
| D | GUI scene: tube coloured by temperature, particles by gas density, blue sky, pressure strip, calculations panel, exaggeration switch | `sim/static/*` | Checked in a browser: default, fan slow, fan at maximum |
| E | Report regenerated; `project/process-description.md` §2 and `.claude/CLAUDE.md` corrected | `sim/report.py`, `project/*` | Report matches the new model |
| F | Stage 2.1: ring of 60 fireboxes, zones, moving schedule (fire, dampers, doors), no physics | new `sim/kiln/` | The "train" moves at the scheduled rate |
| G | Stage 2.2: flow network (dampers, ring resistance, main flue) joined to stage 1 | `sim/kiln/` | Damper flows sum to the main flue flow |
| H | Stage 2.3-2.4: fuel charges, combustion, gas, brick and tile temperatures, drying | `sim/kiln/` | Energy and mass balances close |
| I | Stage 2.5: kiln plan view, room section, charts and upset controls | `sim/static/*` | Checked in a browser |
| J | Stage 2.6: calibration against logs, upset studies | report in `project/` | Needs the site data in §5 |

Stages A to E are stage 1. Stages F to J are stage 2. Stage J cannot be finished without site data.

Status on 2026-11-17:

| Stage | State | Note |
|---|---|---|
| A | done | Default case gives P1 121 Pa, P2 88 Pa at 380 rpm (site: 119.2 and 87) |
| B | done | Charge and damper disturbances are off by default |
| C | done | `sim/profile.py` |
| D | done | Checked by headless screenshots at default, 100 rpm and 450 rpm. Not checked by eye: true-scale view, light theme, phone width |
| E | done | `project/simulation-report.md` regenerated |
| F | done | `sim/kiln/layout.py`, `sim/kiln/schedule.py` |
| G | done | `sim/kiln/network.py`; the kiln is 0.18 m2 to the fan |
| H to J | not started | |

---

## 3. Design decisions for stages A and B

These replace or refine the stage 1 plan.

### 3.1 Parameters

| Change | Detail |
|---|---|
| Removed | `k_reuse`, `reuse_extraction`, `chimney_diameter_m`, `k_upstream` |
| `kiln_free_area_m2` (new, about 0.18) | Resistance of the kiln and flues up to the fan, written as an equivalent free area: `dP = rho * (Q / A)^2 / 2`. Stage 2 will supply this from the dampers |
| `restriction_free_area_m2` (new, about 0.17) | Unexplained loss between the plate and the chimney top, same form. See §4 |
| `k_fan_to_plate` (new, small) | Short duct from fan to plate, in velocity heads |
| `chimney_bottom_side_m` 1.524, `chimney_top_side_m` 0.914, `chimney_height_m` 38.1 | Owner's dimensions, treated as inside dimensions |
| `fan_efficiency` (new) | For shaft power |
| `t_gas_c` default 130 | Exhaust temperature at the fan and plate |
| `t_amb_c` default 30 | Site climate |
| Duct 1.25 m, plate beta 0.7 | Gives the measured 32 Pa differential at about 3.6 m3/s |
| Fan curve rated at 380 rpm | About 300 Pa rise at the operating point, as the cold-start model assumes |
| Motor and PID range 220-900 rpm, safe speed 380 rpm | Minimum sits above the resonance band; 900 is a placeholder |
| `resonance_low_rpm` 150, `resonance_high_rpm` 210 | The drive holds the nearer edge while the reference is inside the band |
| `p_range_pa` 250, one-sided | Transmitters span 0 to 250 Pa. Below zero the signal saturates just under 4 mA |
| Disturbances | Charge pulse (every 900 s the kiln free area opens for a short time) and a slow drift of the kiln free area (damper cycle) |

### 3.2 Physics

- Kiln gauge pressure now adds to the driving pressure (before, it only shifted P1 and P2).
- Chimney in 20 slices: friction `f * dz / s * rho * v^2 / 2`, wall cooling with perimeter `4 * s`,
  one velocity head lost at the top area.
- Outside air: `p(z) = p_ground * exp(-M * g * z / (R * T))`. Draft is the slice sum of
  `g * (rho_outside - rho_gas) * dz`.
- Pressures are static gauge values; changes of velocity head between sections are ignored, except
  the exit loss.
- The steady solve keeps the damped fixed-point iteration, with a warm start from the last flow so
  the GUI stays fast.

### 3.3 Legacy flow value

`calc_pv` from `fan-ctrl/calculation.py` is called with the simulated P1, P2 (gauge) and T (kelvin)
and the constants from `fan-ctrl/config.py`. It is shown and logged next to the true flow. It does
not drive the PID until its scaling is confirmed (§5).

---

## 4. Finding that shapes stage B

The real reading (P1 119.2 Pa, P2 87 Pa, 130.4 degC, 380 rpm) does not fit the chimney as given.
A 125 ft chimney at 130 degC gives about 120 Pa of draft, so the chimney base should be near
-110 Pa. The site shows +87 Pa. About 200 Pa is lost between P2 and the chimney top, where the
3 ft x 3 ft top accounts for about 10 Pa at a believable flow. `restriction_free_area_m2` stands
for that loss until the cause is known. Candidates: 3 ft and 5 ft are outside dimensions; a damper
or bend after the plate; strong cooling in the chimney; P2 tapped somewhere else.

---

## 5. Correction to an earlier statement

`project/whole-kiln-simulation-plan.md` §7 item 4 says the legacy formula gives about 1608 or 65
for the screenshot reading. Those figures placed the `* 1000` outside the square root. With the
formula exactly as coded (`* 1000` inside the square root, gauge pressure ratio, T in kelvin):

| Plate area constant `a2` | Result |
|---|---|
| `0.6096 ** 2` = 0.3716 (default in `fan-ctrl/config.py`) | 31.0 |
| 0.6096 (VelKilnMaster document) | 50.9 |
| Screen value "Q Aver" | 40.33 |

The screen value is an average and lies between the two. Which `a2` the legacy system uses is
still open; the LabVIEW logs will settle it.

---

## 6. Open items that block calibration, not the build

1. Inside dimensions of the chimney, and what sits between the plate and the chimney.
2. Fan curve or nameplate; real maximum speed.
3. LabVIEW minute logs (`C:\Labview-Logs\`) for more operating points.
4. Stage 2 data listed in `project/whole-kiln-simulation-plan.md` §5.
