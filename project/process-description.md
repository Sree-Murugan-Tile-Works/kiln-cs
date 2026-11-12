# Process Description

Physical process context for `kiln-cs`, as described by the project owner. Complements
`project/hardware-overview.md` (which covers the devices and PLC/drive links). Items not yet
confirmed are marked **(verify)**; unanswered questions are in §8.

## 1. The process

- A wood-fired **kiln** (Hoffman-type continuous kiln, see `hardware-overview.md` §1) produces
  hot exhaust gas.
- The exhaust is **flue gas from burning firewood**: mostly N2, plus CO2, water vapour,
  leftover O2, and possibly smoke, tar and particulates. It is not clean air.
- The exhaust is **ducted to other uses to recover and reuse the heat**.
- Flow through the duct has two drivers:
  1. **Natural draft** — buoyancy of the hot gas plus the **chimney** stack effect. The
     chimney sits on the far side of the fan and adds its own suction.
  2. **The fan** — used when natural draft is not enough to achieve and control the required
     flow. The fan's effect on flow is therefore not constant: it depends on how much natural
     draft exists at that moment (weather, kiln temperature, chimney conditions).
- Gas flow is measured across an **orifice plate** in the duct, upstream of the fan.

```
kiln --> [duct] --> orifice plate (P1 | P2, T) --> [heat-reuse ducts] ... --> fan --> chimney
```

The order of the plate, the heat-reuse branches and the fan is **(verify)** — see §8.

## 2. Instruments

| Signal | Measures | Notes |
|---|---|---|
| P1 | Duct pressure upstream of the plate | Differential transmitter, low side open to room. Reads **gauge** pressure (`P_duct - P_room`) |
| P2 | Duct pressure downstream of the plate | Same arrangement as P1 |
| T | Gas temperature in the duct | Hot flue gas, at/near the plate |
| Ambient T | Room/ambient temperature | Additional sensor. Intended use not yet decided (§8) |

The owner describes P1/P2 as "used as absolute pressure sensors". Physically they are
**gauge-via-differential** sensors: a differential transmitter with its low side open to the
room reads `P_duct - P_room`. They are not true absolute sensors (no vacuum reference). Use the
term "gauge-via-DP" in docs and code comments so nobody assumes the values are absolute.

Consequences:

- The plate pressure drop `P1 - P2` is unaffected (room pressure cancels).
- Anything that needs true absolute pressure must add `P_atm` (a configured constant or a
  barometer reading, **not yet available**).
- If the duct is under suction, P1/P2 can be near zero or negative, so a bare ratio `P2/P1`
  of gauge values is numerically fragile.

## 3. The flow equation is empirical

`fan-ctrl/calculation.py: calc_pv` looks like the standard compressible-flow orifice equation,
but it is **not** a clean engineering calculation. Per the owner, it was tweaked about 20+
years ago in the previous control system until it gave the desired results. Some constants
are tuned values and are **not** in exact engineering units or calibration.

Rules that follow:

- **Do not "correct" `c`, `a2`, `z`, `r`, `m`, `k`, the `* 1000` factor, or the temperature /
  pressure unit handling to textbook values.** The suspicious-looking values (for example
  `m = 89`, T possibly in Celsius, gauge pressures in a ratio) may be compensating for one
  another. The site's existing results are the reference.
- **Preserve behaviour first.** Before any refactor of `calc_pv` or its inputs, capture
  characterisation (golden) tests: known inputs and the outputs the current code gives, plus
  real data from the old system if any can be found.
- Any change to the equation is a deliberate recalibration decision for the owner, not a
  cleanup.
- Wood flue gas composition varies with wood moisture and firing stage, which is another
  reason the constants are best treated as tunable calibration values.

## 4. Operating considerations (hardware side)

- Tar and condensate can foul or block impulse lines and plate bores in wood flue gas,
  causing drifting or stuck pressure readings. Software should eventually flag stuck or
  implausible readings (see the existing `plc_ai_error` sentinel handling).
- The temperature at the plate is only valid at the plate; heat extraction elsewhere changes
  the temperature downstream.

## 5. Scope of the current change

- The **plate, the instruments, the kiln and the chimney remain the same.** What is being
  replaced is the **control system** (the fan-ctrl / PLC / drive side described in
  `hardware-overview.md`).
- Direction agreed with the owner: improve the system slowly, control system first.

## 6. Planned roadmap

1. Document process and context (this file).
2. Get the new control system working, preserving the existing flow-equation behaviour
   (characterisation tests first).
3. Later: a **visual, GUI-based simulation** of the whole process (kiln, duct, plate, fan,
   chimney, natural draft) so control behaviour can be developed and tested on the dev
   machine, in line with the "dev machine first, hardware last" rule.

The simulation is not designed yet. A plan document will be written under `project/` for
review before any implementation.

## 7. Open design questions for the control strategy

- Is the setpoint a flow `Q` (as today), or ultimately a duct draft/pressure?
- May the fan drop to zero when natural draft alone meets the setpoint, or is there a
  minimum speed?
- Is ambient temperature intended for logging, density/draft compensation or feed-forward?
- Is PID alone sufficient, or is feed-forward for natural draft wanted?

## 8. Open questions (unanswered)

- [ ] Position of the plate relative to the heat-reuse branches and the fan.
- [ ] Realistic temperature range at the plate.
- [ ] Transmitter ranges and normal/maximum plate pressure drop; units behind the `±250`
  engineering range.
- [ ] Is the duct pressure at the plate negative (suction)?
- [ ] What did the old system feed into the equation (pressure units, T in C or K)?
- [ ] Does any record of the old system exist (original equation, constants, logged
  P1/P2/T/Q data)? Is the `calculation.py` `__main__` example a real operating point?
- [ ] Is the formula to stay frozen long term, or eventually re-derived and recalibrated?
- [ ] What exactly is changing in the "control system" (hardware, software, both)?
- [ ] Barometer available, or use a configured `P_atm` constant?
