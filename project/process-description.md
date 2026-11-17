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
- Gas flow is measured across an **orifice plate** in the duct, **between the fan and the chimney**
  (owner correction, 2026-11-16; earlier versions of this document had it upstream of the fan).

```
kiln and flues --> fan --> [short duct] --> orifice plate (P1 | P2, T) --> chimney
```

Because the plate is on the fan's discharge side, P1 and P2 are positive when the fan pushes hard
and would be negative on natural draft alone. One site reading (LabVIEW screen, 17-03-2026) shows
P1 119.2 Pa and P2 87 Pa at 130.4 degC and 380 rpm. The chimney is 125 ft tall and square, 5 ft at
the base and 3 ft at the top (owner, 2026-11-16; another document says 120 ft).

Heat reuse happens inside the kiln's own tunnels, before the fan (owner, 2026-11-14). It is not of
interest for the flow control and is no longer modelled in the simulation. What sits between the
plate and the chimney is **(verify)**: the site reading implies about 200 Pa of loss there that the
chimney dimensions do not explain. See `project/simulation-report.md` §3.

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

- The **plate, the instruments, the kiln and the chimney remain the same.** What changes is
  the **control system**. Agreed 2026-11-14 (this replaces the 2026-11-13 idea of swapping the
  PLC, HMI and VFD): the Omron PLC, the Weintek HMI and the ABB ACS560 **stay**, and a
  **Raspberry Pi 5 Compute Module is added** to do the flow calculation (the PLC has no square
  root), logging and the web interface. If the Pi fails the PLC continues from a lookup table
  (see `hardware-overview.md` §10).
- Direction agreed with the owner: improve the system slowly, control system first.
- Safety design is explicit because a Pi sits in the loop while healthy: heartbeat and lookup
  table fallback, fixed safe RPM on sensor failure, drive comms-loss action, hardwired
  run/stop and E-stop, and the Pi never stops the fan (`hardware-overview.md` §10.5).

## 6. Planned roadmap

1. Document process and context (this file).
2. Build the Pi supervisor on the dev machine: a simulated PLC link and drive with the same
   data shape as the real ones, preserving the existing flow-equation behaviour
   (characterisation tests first), the fallback table generator and failure drills. Then
   log-only on site, then let the Pi feed the PLC (phases in `hardware-overview.md` §10.8).
3. Later: a **visual, GUI-based simulation** of the whole process (kiln, duct, plate, fan,
   chimney, natural draft) so control behaviour can be developed and tested on the dev
   machine, in line with the "dev machine first, hardware last" rule.

Status 2026-11-14: a first version exists in `sim/` (parametric physics model, closed loop on the
real PID code, web GUI with sliders; run `python -m sim.server`). How the parameters affect each other
is written up in `project/simulation-report.md`. All values in it are placeholders until site data is
available.

## 7. Open design questions for the control strategy

- Is the setpoint a flow `Q` (as today), or ultimately a duct draft/pressure?
- May the fan drop to zero when natural draft alone meets the setpoint, or is there a
  minimum speed?
- Is ambient temperature intended for logging, density/draft compensation or feed-forward?
- Is PID alone sufficient, or is feed-forward for natural draft wanted?

## 8. Open questions (unanswered)

- [x] Position of the plate: answered 2026-11-16 — between the fan and the chimney. Heat reuse is
  inside the kiln tunnels, before the fan (2026-11-14).
- [ ] What is between the plate and the chimney, and are the chimney's 3 ft and 5 ft inside or outside
  dimensions? (About 200 Pa of unexplained loss, `project/simulation-report.md` §3.)
- [ ] Realistic temperature range at the plate (one reading: 130.4 degC).
- [x] Transmitter ranges: P1 and P2 are 0-250 Pa (VelKilnMaster `docs/Kiln-Domain.md`). The `±250`
  defaults in `fan-ctrl/config.py` do not match and need a decision.
- [x] Is the duct pressure at the plate negative (suction)? No at normal speed: P1 119.2 Pa and P2 87 Pa
  at 380 rpm. The simulation suggests it turns negative below about 245 rpm, where a 0-250 Pa
  transmitter cannot read it.
- [ ] What did the old system feed into the equation (pressure units, T in C or K)?
- [ ] Does any record of the old system exist (original equation, constants, logged
  P1/P2/T/Q data)? Is the `calculation.py` `__main__` example a real operating point?
- [ ] Is the formula to stay frozen long term, or eventually re-derived and recalibrated?
- [x] What is changing in the "control system"? Answered 2026-11-14: PLC, HMI and ACS560 stay;
  a Pi is added as supervisor (flow calculation, logging, web UI, fallback table). This
  replaces the 2026-11-13 answer (PLC, HMI and VFD replaced).
- [x] Sensor interface, VFD and HMI connection: sensors stay on the PLC, the ACS560 stays, the
  HMI bridges the drive over Modbus (`hardware-overview.md` §10).
- [ ] Behaviour on power cut or hung controller today; hardwired E-stop wiring and manual
  bypass (`hardware-overview.md` §10.10).
- [x] Cutover plan: log first (Pi read-only), then the Pi feeds the PLC, with drills at each
  phase (`hardware-overview.md` §10.8).
- [ ] Barometer available, or use a configured `P_atm` constant?
