# Simulation upgrade plan

**Status:** draft for team review, 2026-11-16. Nothing in this plan is implemented yet.
**Scope:** the process simulation in `sim/` and its GUI only. No change to `fan-ctrl/`, `dashboard/`
or any hardware. All parameter values remain placeholders, not measured site data, except the
chimney dimensions given by the owner below.

---

## 1. Why

The owner reviewed the first simulation (2026-11-16) and asked for:

1. The flow meter (orifice plate) placed **between the fan and the chimney**. The current model has
   it before the fan.
2. Heat reuse inside the kiln **removed** from the model. It is not of interest.
3. A **parametric chimney**: 125 ft tall, 3 ft x 3 ft at the top, 5 ft x 5 ft at the bottom.
4. A richer picture: a tube whose **colour shows temperature**, **particles** that show how dense
   the gas is, a **blue sky** with particles that show the air at the height of the chimney.
5. **More calculations** shown from the same model.

A fresh read of the code also found that the chimney is solved as one lump with a single mean
temperature, and the outside air has the same pressure and density at every height.

---

## 2. Process layout

Today:

```
kiln (heat-reuse tunnels) --> duct --> orifice plate (P1 | P2, T) --> fan --> chimney
```

Proposed:

```
kiln --> duct --> fan --> short duct --> orifice plate (P1 | P2, T) --> chimney --> sky
```

Consequences of moving the plate to the fan discharge:

- P1 and P2 are no longer always suction. They sit near the chimney-base pressure, so they are
  **negative when draft dominates and can turn positive when the fan pushes hard**.
- The transmitter range (`p_range_pa`) and the PLC count scaling must be re-checked against the new
  pressures.
- The gas at the plate is the gas leaving the fan. The model keeps the same temperature across the
  fan (fan heating is ignored).

`project/process-description.md` §2 currently says the plate is upstream of the fan. It will be
corrected when this plan is implemented.

---

## 3. Physics changes

### 3.1 Heat reuse removed

- Parameters `k_reuse` and `reuse_extraction` are deleted.
- `t_gas_c` becomes "gas temperature leaving the kiln" and is the temperature at the fan and plate.
- The separate kiln and plate temperatures (`t_kiln_c`, `t_plate_c`) collapse into one.
- Any resistance inside the kiln is covered by the existing `k_upstream` (kiln exit to fan).

### 3.2 Tapered square chimney

New parameters (SI internally, shown with feet alongside in the GUI):

| Parameter | Default | Meaning |
|---|---|---|
| `chimney_height_m` | 38.1 m (125 ft) | Height from base to top |
| `chimney_bottom_side_m` | 1.524 m (5 ft) | Inside side length at the base |
| `chimney_top_side_m` | 0.914 m (3 ft) | Inside side length at the top |

`chimney_diameter_m` is deleted. The side length varies linearly with height. Whether 3 ft and
5 ft are inside or outside dimensions is an open question (§8); the model treats them as inside.

The chimney is solved in about 20 slices from base to top. In each slice of height `dz` with side
`s`, for mass flow `m`:

- velocity `v = m / (rho * s^2)`
- friction `dP = f * (dz / s) * rho * v^2 / 2` (hydraulic diameter of a square is its side)
- wall heat loss `dT = -U * 4 * s * dz * (T - T_amb) / (m * cp)`
- density from the slice temperature

The exit loss is one velocity head at the **top** area. Because the top is 2.8 times smaller in
area than the base, exit velocity and exit loss are much larger than in the current model.

### 3.3 Atmosphere with height

Outside air pressure follows the barometric formula:

```
p(z) = p_ground * exp(-M_air * g * z / (R * T_amb))
```

At 38.1 m and 25 degC this is about 440 Pa (0.44 %) below ground pressure. Outside air density is
computed per slice from `p(z)`.

Natural draft becomes a slice-by-slice sum instead of one product:

```
draft = g * sum( (rho_outside(z) - rho_gas(z)) * dz )
```

### 3.4 Pressure walk (gauge, room at ground level = 0)

| Station | Pressure |
|---|---|
| Kiln | `kiln_gauge_pa` |
| Fan inlet | kiln minus the kiln-to-fan duct loss |
| Fan outlet | fan inlet plus the fan pressure rise |
| P1 | fan outlet minus the fan-to-plate duct loss (new parameter `k_fan_to_plate`, small) |
| P2 | P1 minus the full plate differential |
| Chimney base | P1 minus the plate's permanent loss |
| Chimney, any height | reported relative to the outside air at the same height |
| Chimney top | zero relative to the outside air there |

The steady solve stays a damped fixed-point iteration on mass flow. Existing simplifications stay:
incompressible pressure balance, no flow reversal, stopped fan is a passive resistance.

### 3.5 Defaults to retune

The taller chimney gives more draft, so the default setpoint (4.5 m3/s) may be reachable with no
fan. Placeholder fan and setpoint defaults will be adjusted so the default case needs the fan and
P1/P2 stay inside the transmitter range. The chosen values will be listed in the report.

---

## 4. New calculations

All computed in Python and sent to the browser. Nothing is calculated in JavaScript.

| Group | Values |
|---|---|
| Flow | Mass flow; volumetric flow at the plate; share of flow from draft and from the fan |
| Velocity | Duct, plate bore, chimney base, chimney exit; Reynolds number in the duct and chimney |
| Pressure | Gauge and absolute pressure at every station; air pressure at ground and at chimney top |
| Pressure budget | Draft + fan rise = kiln-to-fan duct + fan-to-plate duct + plate permanent loss + chimney friction + exit loss |
| Density | Gas at each station; outside air at ground and at chimney top |
| Power | Fan air power (`Q * dP`); estimated shaft power using a new `fan_efficiency` parameter |
| Heat | Heat carried by the gas above ambient; heat lost through the chimney wall |
| Temperature | Along the whole path, including the chimney profile and the exit temperature |

The Reynolds number needs gas viscosity; an air approximation (Sutherland's formula) is used and
labelled as such.

---

## 5. Visuals

### 5.1 Scene

One canvas, drawn in proportion, replacing the small line drawing:

- Ground line, kiln, horizontal duct, fan (blades turn with rpm), plate with the P1 and P2 taps,
  tall tapered chimney, blue sky.
- **Tube colour = gas temperature**, as a continuous gradient along the path and up the chimney,
  with a colour legend in degC.
- **Particles inside the tube**: how many are drawn follows the gas density; how fast they move
  follows the gas velocity at that point. They speed up as the chimney narrows.
- **Particles in the sky**: static, with density following the outside air at that height.
- Numeric labels at each station, and the air pressure and density at ground and at chimney top.

### 5.2 What the particles mean

Owner decision 2026-11-16: particles represent air density / pressure. Design:

- Particle count per unit area is proportional to the number of gas molecules per unit volume,
  which is `pressure / temperature`. This responds to both pressure and temperature.
- At true scale the hot gas in the tube is visibly thinner than the outside air (about 37 % fewer
  particles at 200 degC). This difference is what drives the draft.
- At true scale the sky thins by only 0.44 % over the chimney height, and tube pressures differ
  from atmospheric by well under 1 %. Neither would be visible.
- Therefore the scene has an **"Exaggerate pressure" switch**. Off: true scale. On: the pressure
  part of the particle count is multiplied by a stated factor so the thinning with height and the
  suction and pressure zones along the tube become visible. The scene shows a "not to scale" note
  while it is on. The numeric labels always show true values.

### 5.3 Pressure strip

A chart under the scene, aligned with it, showing gauge pressure along the path from kiln to
chimney top. It shows the suction before the fan, the fan's step up, the plate's step down and
the recovery to zero at the top.

### 5.4 Other GUI changes

- A "Calculations" panel for the values in §4, including the pressure budget as a stacked bar.
- Chimney sliders show metres and feet.
- The four history charts stay; the temperature chart loses the "before reuse" series.

### 5.5 Data path

- `GET /api/state` gains a `profile` field for the latest instant only: a list of stations with
  position, height, tube size, temperature, gauge and absolute pressure, density and velocity, plus
  the outside air at matching heights and the calculation values.
- The profile is not stored per history record, so the history size does not grow.
- The browser animates with `requestAnimationFrame` between the 300 ms polls.

---

## 6. Files that will change

| File | Change |
|---|---|
| `sim/gas.py` | Barometric pressure, viscosity helper |
| `sim/params.py` | Remove reuse and round-chimney parameters; add tapered chimney, `k_fan_to_plate`, `fan_efficiency`; retuned defaults |
| `sim/plant.py` | New layout, sliced chimney, pressure walk, profile and derived values |
| `sim/loop.py` | Record fields follow the new operating point; temperature transmitter reads the single gas temperature |
| `sim/server.py` | `profile` in the state snapshot |
| `sim/analysis.py`, `sim/report.py` | Drop the reuse study; use the new chimney parameters; add a chimney taper study |
| `sim/static/index.html`, `app.js`, `style.css` | Canvas scene, pressure strip, calculations panel |
| `tests/sim/*` | Updated for the new layout; new tests listed in §7 |
| `project/simulation-report.md` and figures | Regenerated with `python -m sim.report` |
| `project/process-description.md` | Plate position corrected in §2 |
| `.claude/CLAUDE.md`, `TODO.md`, `Claude_log.md` | Test count, task status, session record |

---

## 7. Tests

Existing behaviour tests are kept where the physics is unchanged (draft rises with height and gas
temperature, flow rises with fan speed, plate differential scales with flow squared, estimator
recovers the true flow). New tests:

- Pressure balance closes with the new station order at several fan speeds.
- P1 and P2 are negative under draft alone and rise as fan speed rises.
- A straight chimney (top side = bottom side) reproduces the single-lump formula within tolerance.
- A narrower top raises exit velocity and lowers flow.
- Slice count does not change the answer beyond a small tolerance.
- Barometric pressure at 38.1 m matches the hand value (about 440 Pa drop at 25 degC).
- Mass is conserved along the profile (`rho * v * area` equal at every station).
- Fan air power, heat carried and wall heat loss match hand calculations at one operating point.
- `/api/state` returns a well-formed `profile`; removed parameters are rejected by `/api/params`.

Acceptance: `pytest` passes from the project root, the GUI runs with `python -m sim.server`, and
the scene has been checked in a browser at default settings, fan stopped, and fan at maximum.

---

## 8. Open questions

1. Are 3 ft and 5 ft the **inside** dimensions of the chimney, or outside? The model needs inside.
2. Is the chimney brick, steel or lined? This sets the friction factor and wall heat loss.
3. What is between the fan and the plate, and how long is that duct?
4. Is the duct round or square, and what size is it at the plate?
5. Does the chimney base sit at the same level as the duct, or is there a vertical rise first?
6. Is the exaggeration switch in §5.2 acceptable, or should particles always be true scale?

---

## 9. Order of work

One pass on the dev machine after approval:

1. Physics and parameters, with tests.
2. Loop, server profile and analysis, with tests.
3. GUI scene, pressure strip and calculations panel; checked in a browser.
4. Regenerate the report; update the docs listed in §6.
