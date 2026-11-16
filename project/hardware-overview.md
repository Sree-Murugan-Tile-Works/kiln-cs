# Field Hardware Overview

> **Status (2026-11-14): the PLC, the HMI and the ACS560 STAY in service.** A Raspberry Pi 5
> Compute Module is **added** as a supervisor (flow calculation, logging, web interface,
> fallback table loader). If the Pi fails, the PLC continues from a lookup table. This
> supersedes the 2026-11-13 direction that the PLC, HMI and software would be replaced.
> The agreed architecture, fail-safe plan and execution plan are in §10; sections 2 and
> 4–6 describe how the existing system is wired and remain accurate.

This document captures the real field hardware behind `kiln-cs`, as described by the
project owner, and maps each physical device/sensor onto the existing `fan-ctrl`/`dashboard`
code. Items that are inferred rather than directly confirmed are marked **(verify)**.

## 1. Application

The system controls combustion-air / draft fan speed on a **Hoffman-type continuous kiln**,
regulating the flow of exhaust gas leaving the kiln by varying fan RPM in response to a
flow measurement taken across an orifice plate.

## 2. Hardware Inventory (current system, stays in service — see §10)

| Component | Model | Role |
|---|---|---|
| HMI | Weintek cMT3072XH | Local operator touch panel — independent of the `dashboard/` Flask app, talks to the PLC directly |
| PLC | Omron CP2E-N30DT1-D | Field I/O concentrator; reads P1/P2/T sensors, drives the fan reference; the only thing `fan-ctrl/plc.py` talks to |
| Fan drive | ABB ACS560-01-12A6-4 | VFD that actually spins the combustion-air fan motor at the commanded RPM |
| Flow element | Orifice plate | Fixed restriction in the duct; the pressure drop it creates is the basis for the flow calculation in `calculation.calc_pv` |
| Pressure transmitter 1 (P1) | unspecified **(verify)** | High side connected **upstream** of the orifice plate; low side vented to room/atmospheric pressure |
| Pressure transmitter 2 (P2) | unspecified **(verify)** | High side connected **downstream** of the orifice plate; low side also vented to room/atmospheric pressure |
| Temperature transmitter | Novus TxRail-USB (DIN rail, 4–20 mA / 0–10 V) — see §11.1 | Measures gas temperature at/near the orifice plate; feeds `T` in the flow equation. Probe type (Pt100 / thermocouple) and programmed range **(verify)** |

## 3. Physical Sensor Topology

The two pressure transmitters are **not** a single differential-pressure (ΔP) transmitter
straddling the orifice plate. They are two separate **gauge** transmitters:

```
        room pressure (vent)              room pressure (vent)
                |                                  |
              [P1 lo]                            [P2 lo]
                |                                  |
duct  --------[P1 hi]---- orifice plate ----[P2 hi]--------  duct
      (upstream)                           (downstream)
```

- `P1` = upstream gauge pressure, `P2` = downstream gauge pressure, both relative to room
  (atmospheric) pressure.
- This matches the code: `calculation.calc_pv` takes `p1`/`p2` as independent readings and
  uses the ratio `p2/p1`, rather than consuming a single ΔP signal.
- **Important nuance (see §7):** because both signals are *gauge*, not *absolute*,
  `p2/p1` is the ratio of two small numbers near zero (engineering range is configured as
  `±250` on each — see `config.parameters_definition`), not the ratio of two large
  near-atmospheric absolute pressures. Whether the orifice-flow formula as coded expects
  gauge or absolute pressures here is worth double-checking — see §7.

## 4. PLC ↔ Python Link (`fan-ctrl/plc.py`) — stays, becomes the Pi-to-PLC link (see §10)

- Protocol: Omron FINS over TCP (`fins.tcp.TCPFinsConnection`), driven by `config_params`:
  `plc_ip`, `plc_fins_port` (default `9600`), `dest_node_address`, `src_node_address`.
- Today this is **fully stubbed** — `connect()` opens a real FINS TCP socket, but
  `read_all()`/`write()`/`read_dm()`/`write_dm()` never use it; they return hardcoded raw
  values (`p1_raw=4500`, `p2_raw=4200`, `t_raw=3360`). Wiring these up to real DM register
  reads/writes on the CP2E-N30DT1-D is the main blocker before this runs against hardware.
- `cfg.plc_ai_error` (default `8000`) is the sentinel raw value `read_all` checks for to
  detect a sensor fault on a given analog input channel — consistent with Omron analog
  input units reporting a fixed out-of-range/burnout code rather than a normal scaled value
  **(verify this is the actual fault code your AI module/firmware uses)**.
- **(verify)** The CP2E-N30DT1-D base unit's built-in I/O is digital (`N30` = 30 I/O points,
  `DT1` = transistor/NPN outputs). Reading 3 analog sensors (P1, P2, T) and writing an
  analog or pulse speed reference likely requires an analog I/O expansion unit on the CP2E —
  confirm this is fitted/planned.

## 5. HMI Relationship to This Codebase (Weintek HMI stays, see §10)

The Weintek cMT3072XH is a separate, local operator panel that talks to the PLC directly —
it is **not** the same thing as `dashboard/web.py` (which is a remote/web view reading
`data.db`/`config.db`). Two things worth resolving before relying on both:

- If the HMI can write setpoints/commands into the same PLC memory area that the Python
  `fan-ctrl` daemon reads/writes, there's a potential conflict: the daemon currently treats
  `config.db`'s `cur_cmd` as the single source of truth for PID/MAN/OFF mode, and writes
  the computed RPM back to the PLC every scan. If the HMI can also write to the PLC
  independently, the two control paths could fight each other unless one is designated
  authoritative.
- This isn't yet a problem in code (since `plc.py` I/O is fully stubbed), but it's worth
  deciding before wiring up real reads/writes.

## 6. PLC ↔ Drive Link (Omron CP2E ↔ ABB ACS560): resolved 2026-11-14, the HMI bridges over Modbus (see §10)

Decided 2026-11-14 (§10.2, decision 12): the HMI reads the demanded RPM from the PLC and writes
it to the ACS560 over RS-485 Modbus RTU. The Pi never talks to the drive, and
`KilnPLC.write()` no longer carries a commanded RPM (§10.9).

Two points from the 2026-11-16 review are still open (`connection-diagram.md` §6.3 and §8):

- **How the speed reaches the drive today is unconfirmed.** Deck slide 5 draws a pulse train
  from the PLC to the drive. The CP2E has pulse/PWM outputs and no analog output, and the
  drive's DI5 can be a frequency input (0–16 kHz), so a direct PLC-to-drive signal probably
  exists **(verify)**.
- **Moving the reference to the HMI puts the HMI inside the control loop.** Keeping the
  existing signal, or a PLC serial option board with the Modbus-RTU Easy Master, would keep it
  out. To be decided before Phase 4.

## 7. Orifice-Plate Flow Formula, Variable by Variable

`fan-ctrl/calculation.py: calc_pv`:

```python
Q = C * A2 * sqrt(
        (2 * Z * R * T / M) * (K / (K - 1)) *
        ((P2/P1)**(2/K) - (P2/P1)**((K+1)/K)) *
        1000
    )
```

This is the standard compressible-flow-through-a-restriction equation (the same family used
for orifice/nozzle gas flow metering). Each symbol, where it comes from physically, and its
`config_params` name/default:

| Symbol | Meaning | Physical source | Config name | Default |
|---|---|---|---|---|
| `C` | Discharge coefficient of the orifice plate (dimensionless, accounts for real vs. ideal flow through the opening) | Fixed property of the plate geometry/installation, normally from the plate's calibration sheet or a standard (ISO 5167 / similar) | `c` | `0.7` |
| `A2` | Effective flow area term used by this formula | Orifice plate bore geometry | `a2` | `0.6096**2 ≈ 0.3716` |
| `Z` | Gas compressibility factor | Gas property, ~1.0 for near-ideal gas behavior | `z` | `0.981213836` |
| `R` | Universal gas constant | Physical constant, `8.31446 J/(mol·K)` | `r` | `8.31445` |
| `T` | Absolute gas temperature at the orifice | Temperature sensor reading | `cfg.t_eng_min/max` = `0`–`250` (looks like °C, not K — see caveat below) |
| `M` | Molecular weight of the gas | Composition of the kiln exhaust gas | `m` | `89` |
| `K` | Ratio of specific heats (Cp/Cv) | Gas property; `1.4` is the ideal-diatomic-gas value (air, N₂, O₂) | `k` | `1.4` |
| `P1` | Upstream gauge pressure | Pressure transmitter 1 | scaled via `p1_eng_min/max = -250..250` |
| `P2` | Downstream gauge pressure | Pressure transmitter 2 | scaled via `p2_eng_min/max = -250..250` |

All of these are editable live from the dashboard `/config` page (`config_params` table),
not hardcoded — see `fan-ctrl/config.py: parameters_definition`.

### Things worth verifying against the real instrumentation (not asserted as bugs — these
depend on calibration choices made when the constants above were derived):

1. **Gauge vs. absolute pressure.** The formula's `(P2/P1)` ratio comes from the isentropic
   flow derivation, which assumes **absolute** pressures. Both transmitters here are gauge
   (vented to atmosphere — §3), with a small engineering range (`±250`, presumably mmWC or
   a similar draft-pressure unit, not kPa-scale absolute). If `P1`/`P2` are fed into
   `calc_pv` as raw gauge values rather than `atmospheric + gauge`, the computed ratio could
   diverge substantially from the true absolute-pressure ratio the formula expects —
   especially since this is a draft/exhaust application where gauge pressure may even cross
   zero or go negative (suction). Worth confirming whether the other constants (`c`, `z`,
   etc.) were empirically tuned to compensate for this, or whether an atmospheric offset
   needs to be added before computing `p2by1`.
2. **Celsius vs. Kelvin.** The ideal-gas term `2*Z*R*T/M` assumes `T` is an **absolute**
   temperature (Kelvin). `t_eng_min/max = 0..250` strongly suggests `T` is configured in
   Celsius. If so, `T` should likely be converted to Kelvin (`+273.15`) before use, unless
   that offset has been folded into one of the other constants.
3. **Molecular weight `M = 89`.** Typical air/combustion flue gas is ~28–30 g/mol, not 89.
   This may be a deliberate site-specific value (different gas composition in this kiln's
   exhaust) or a placeholder default that hasn't been tuned yet — worth confirming against
   an actual flue-gas analysis if available.
4. **The trailing `* 1000`** inside the square root is a unit-conversion constant reconciling
   whatever units `R`, `M`, and the pressures are expressed in with the desired output units
   for `Q`. Worth tracing through once the units in points 1–3 above are confirmed, so the
   final `Q`/`q_avg` values can be labeled with a real engineering unit (currently they're
   dimensionless to the code — `kiln_data.q_value`/`q_avg` have no unit annotation anywhere).

None of this requires code changes yet — it's a calibration/verification exercise once the
real transmitters are installed and can be cross-checked against an independent flow
reading.

## 8. Raw-to-Engineering Scaling

`calculation.Scaler` linearly maps PLC raw analog-input counts to engineering units:

- `p1_plc_min/max = 0..6000` (raw counts) → `p1_eng_min/max = -250..250` (engineering units)
- Same pattern for `p2_*` and `t_*` (`t_eng_min/max = 0..250`)
- `rpm_plc_min/max` / `rpm_eng_min/max` exist in `config_params` for the same kind of
  scaling on the motor RPM read-back path, though nothing in `plc.py` uses them yet (`write()`
  is still a stub).

## 9. Open Questions / To Verify

- [ ] Exact models/ranges/output signal (4–20mA? 0–10V?) of the two pressure transmitters
  and the temperature sensor.
- [ ] Does the CP2E-N30DT1-D have (or will it get) the analog I/O expansion module(s) needed
  to read 3 analog channels and drive the fan reference?
- [ ] PLC ↔ ACS560 command path: analog reference vs. Modbus RTU vs. fieldbus module (§6).
- [ ] Whether the Weintek HMI can independently write to PLC memory the Python daemon also
  controls, and if so, which side is authoritative (§5).
- [ ] Gauge-vs-absolute pressure and Celsius-vs-Kelvin temperature assumptions in
  `calc_pv` (§7, points 1–2).
- [ ] Real-world value/justification for molecular weight `M = 89` (§7, point 3).

These are tracked as follow-up items in `TODO.md`.

> Note (2026-11-13): items in §7 describe how `calc_pv` looks against textbook engineering.
> The owner has stated the equation was empirically tuned ~20+ years ago, so these are
> *verification* points, not fixes to apply. See `project/process-description.md` §3.

## 10. Control Architecture (agreed 2026-11-14)

> **Supersedes the 2026-11-13 direction** ("a Pi, a new HMI and a new VFD replace the PLC, HMI
> and software"). The Omron PLC, the Weintek HMI and the ABB ACS560 **stay in service**. A
> Raspberry Pi 5 Compute Module is **added** as a supervisor. A shareable approval page
> exists (private until the owner shares it): https://claude.ai/artifact/QTxBwFJL4baTap6qoHf4Ba

Status labels: **decided** = agreed with the owner in the 2026-11-14 design discussion;
**proposed** = suggested, not yet agreed; **open** = needs a value or a decision.

### 10.1 Principle

The PLC and HMI are the reliable layer. The Pi is allowed to fail. The PLC cannot do a square
root (no such instruction in the CP1E/CP2E instruction reference; floating-point add,
subtract, multiply and divide exist), so the Pi does the flow calculation. If the Pi stops,
the PLC continues from a lookup table.

### 10.2 Who drives what

| Function | Owner | How | If the owner fails |
|---|---|---|---|
| Read P1, P2, duct T | PLC | CP1W-AD041 analog unit, 0–6000 counts, 8000 = open circuit (§11.3) | Fixed safe RPM and alarm (**decided**) |
| Flow calculation (square root) | Pi | Existing `calc_pv`, unchanged. Reads counts from the PLC, writes flow and a heartbeat back (**decided**) | PLC uses its lookup table (**proposed**) |
| PID loop | PLC | PLC PID with the existing constants (**decided**). Textbook Python PID is used for simulation only; whether to match the PLC's PIDAT form is decided after simulation (§12.7) | **open** |
| Speed to the drive | HMI | Reads demanded RPM from the PLC, writes it to the ACS560 over RS-485 Modbus RTU (X5), reads status back (**decided**) | Drive comms-loss action goes to a safe speed (**decided**, parameters **open**) |
| Run / stop | Hardwired operator switch | Drive input DI1. The Pi never stops the fan; a software `OFF` means "go to safe speed" (**decided**) | Independent of every computer |
| Emergency stop | Hardwired E-stop | Drive Safe Torque Off inputs (**decided**, wiring to verify) | Independent of every computer |
| Logging, history | Pi | SQLite as today | History gap only |
| Changing settings | Pi (Flask) | Setpoint and constants entered on the web page, pushed to the PLC (mechanism **open**) | PLC keeps its last values |
| Fallback lookup table | Pi builds, PLC uses | Table of flow over (P2/P1, T) generated from `calc_pv`, loaded into PLC memory (**decided**) | PLC keeps the last loaded table |
| Operator display on the Pi | Pi | Flask dashboard as a kiosk browser on a monitor attached to the CM5 (**decided**) | Weintek HMI still works |

### 10.3 Connections

```
                           Ethernet (FINS/TCP candidate, protocol open)
                  +---------------------------------------------------+
                  |                                                   |
 sensors --4-20 mA / 0-10 V--> PLC (CP2E-N30DT1-D + CP1W-AD041) <--Ethernet--> HMI (cMT3072XH)
 P1, P2, T                        192.168.100.7              192.168.100.1 (LAN2)
                                                                        |
                                                  RS-485 Modbus RTU, X5 (pins 30 A-, 29 B+, 31 DGND)
                                                                        |
 Pi (Raspberry Pi 5 CM)                                         ACS560-01-12A6-4 --> motor and fan
                                                                        ^
 hardwired: Run/Stop switch --> DI1,  E-stop --> Safe Torque Off -------+
```

- Terminal-level wiring, the network plan, the drive parameters the Modbus link depends on and
  a site verification checklist are in `project/connection-diagram.md` (2026-11-16).
- The HMI's second LAN port (LAN 1, 192.168.16.19) is on the plant network. Which network the
  Pi joins is **open**. The CP2E-N30's two Ethernet ports are a built-in switch (W613), so the
  Pi can plug into PORT B; the PLC allows 3 user FINS/TCP connections plus 1 for CX-Programmer
  (W614).
- The drive has one Modbus master (the HMI). The Pi never talks to the drive.
- Sensors stay wired to the PLC. The Pi needs no ADC and no RS-485; its carrier board only
  needs Ethernet (§11.5).

### 10.4 Normal operation, one scan

1. The PLC reads P1, P2 and duct temperature.
2. The Pi reads those counts from the PLC.
3. The Pi calculates flow (`calc_pv`).
4. The Pi writes the flow and an incrementing heartbeat to the PLC.
5. The PLC's PID runs on that flow against the setpoint and stores the demanded RPM.
6. The HMI reads the demanded RPM and writes it to the drive over Modbus.
7. The drive reports status to the HMI, which passes it to the PLC.
8. The Pi logs readings, flow, RPM and drive status.

While healthy the Pi is inside this loop. That is the reason for the heartbeat and the table.

### 10.5 Fail-safe plan

| What fails | Detection | What happens | Status |
|---|---|---|---|
| Pi stops, crashes or loses the network | Heartbeat does not change for longer than a timeout | PLC switches flow source to the lookup table over (P2/P1, T), PID keeps running. Returns to the Pi after several consecutive good heartbeats to avoid flapping | **proposed**; timeouts **open** |
| A sensor fails (P1, P2, T) | AD041 returns 8000 (loop under 3.2 mA) or value outside its valid band | PLC leaves the PID and sets a fixed safe RPM; alarm on HMI and web page | **decided**; safe RPM **open** |
| HMI fails or the RS-485 link breaks | Drive notices Modbus messages stopped | Drive goes to its configured safe speed by its own comms-loss setting | **decided**; values **open**. Needs 58.14 = Speed ref safe (the default, Fault, trips the drive), 28.41 = safe frequency, 58.16 timeout; the HMI must keep rewriting the reference because reads do not reset the timer with the default 58.15 (`connection-diagram.md` §5.2) |
| PLC fails | HMI sees demanded RPM stop updating | Not decided. Option: HMI writes the safe speed when the PLC value goes stale | **open** |
| Drive fault | Fault relay (RO3) and Modbus status | Drive trips by its own protection; alarm; restart rules to be written | **open** |
| Lookup table unusable (ratio outside the table, or not loaded) | PLC range check before interpolating | Same as a sensor failure: fixed safe RPM and alarm | **proposed** |
| Power cut or restart | Normal power-up | PLC and HMI resume; the Pi boots and re-syncs; the drive runs only if the hardwired run switch is on; the Pi cannot start or stop the fan | restart rules **open** |
| Emergency stop | Operator presses E-stop | Drive removes torque through Safe Torque Off, no software involved | hardware exists, wiring to verify |

Hard rules:

- The Pi can fail without stopping or changing the fan beyond the table behaviour.
- The Pi never stops the fan.
- One control path per signal: no second device writes to the drive.
- Safety functions (run/stop, E-stop, STO) are hardwired.
- Dev machine first, hardware last (`CLAUDE-COMMON.md` Deployment Model).

### 10.6 Fallback lookup table (**decided**, details **open**)

The flow in `calc_pv` is, apart from fixed constants, a function of only the pressure ratio
`r = P2/P1` and temperature `T`. The PLC can compute `r` (it has float divide). So the Pi
evaluates `calc_pv` ahead of time over a grid of (`r`, `T`) and loads the result into PLC
memory; the PLC interpolates. This gives the PID nearly the same flow value without the
square root and without the Pi.

**Simpler form found 2026-11-16 (proposed, replaces the 2-D grid if agreed):** `T` is a plain
multiplier inside the square root, so `Q = g(T) × h(r)` exactly. Two 1-D tables and one
floating-point multiply give the same result as a 2-D table. The CP2E has `APR(069)` for 1-D
line-segment tables with floating-point data (W483); outside the table it holds the end value
instead of extrapolating. DM is kept in non-volatile RAM without a battery (W614), so a loaded
table survives a power cut.

Open points: table spacing and range, scaling of the flow value into the PID's input word
(PIDAT takes an unsigned binary word; the PLC also has floating-point math), behaviour at the
table ends, the step in PID input when switching between the Pi's averaged flow and the
unaveraged table flow, the sign convention of P1/P2 under suction (a ratio above 1 is outside
the formula's domain), and regeneration when the `calc_pv` constants are edited on the
dashboard. The table must be
built from the unchanged `calc_pv`; its constants stay frozen (§CLAUDE.md Key Conventions).

### 10.7 Decisions log (2026-11-14)

| # | Decision | Status |
|---|---|---|
| 1 | ACS560-01-12A6-4 stays (an earlier "replace the VFD" answer was a misclick) | decided |
| 2 | Drive link is hybrid: Modbus RTU for speed and status, hardwired start/stop and STO | decided |
| 3 | Weintek HMI's RS-485 link to the drive carries status only today | decided (owner statement) |
| 4 | Pi shows the Flask dashboard as a kiosk browser; cMT stays as the PLC/drive panel | decided |
| 5 | Sensors stay on the PLC; no ADC on the Pi (earlier "4–20 mA ADC on the Pi" is dropped) | decided |
| 6 | Fixed safe speed on comms loss | decided |
| 7 | Parallel logging phase first, then Pi writes into the PLC | decided |
| 8 | PID stays in the PLC; simulate first with the textbook PID, then decide about the PLC's PIDAT form | decided |
| 9 | The Pi never stops the fan | decided |
| 10 | Carrier board chosen from a requirements list | decided, simpler now (§11.5) |
| 11 | Pi calculates `calc_pv` and writes flow plus heartbeat to the PLC | decided |
| 12 | HMI bridges the demanded RPM to the drive over Modbus | decided |
| 13 | PLC fallback is a 2-D flow table over (P2/P1, T) | decided |

### 10.8 Execution plan (each phase has a gate)

| Phase | Where | Work | Gate |
|---|---|---|---|
| 0 Collect | Site and files | PLC project (CX-Programmer), HMI project, ACS560 parameter backup, how speed leaves the PLC today | Wiring and constants written into these docs |
| 1 Simulate | Dev machine | Simulated PLC link and drive; golden tests for `calc_pv`; table generator and interpolation tests; PID simulation; failure drills (stale heartbeat, bad sensor, lost drive link) | Tests pass; PID form decided |
| 2 Log only | Site, read only | Pi reads PLC counts, calculates and logs flow; PLC controls as today; compare | Agreement within a tolerance the team sets |
| 3 Pi feeds PLC | Site, PLC change | PLC program: flow source selector, heartbeat watch, table lookup, safe-RPM handling; fan on manual or safe speed first; drill: unplug the Pi | Pi-related drills pass |
| 4 HMI drive bridge | Site, drive link | Drive comms-loss action and safe speed set; HMI writes RPM and reads status; drill: disconnect RS-485 | Drive-link drills pass; one Modbus master only |
| 5 Run and handover | Site | Run with documented manual fallback; operator notes; update these docs | Agreed run period without unexplained events |

What can be verified on the dev machine (Phase 1) versus what needs hardware (Phases 2–5)
must be stated in every change proposal (`CLAUDE-COMMON.md`).

### 10.9 Software consequences (**proposed**, nothing implemented yet)

- `fan-ctrl/plc.py` stays as the Pi-to-PLC link (real FINS reads and writes, as already
  planned in `project/implementation-plan.md`), with a simulated twin for the dev machine.
  Its write path changes: instead of writing a commanded RPM it writes the flow and the
  heartbeat, and it reads the counts, the PLC's demanded RPM and status for logging.
- The Pi-side PID (`pid.py`, `fan_drive.py`) is used in simulation. In normal operation the
  PLC runs the loop.
- New: a table generator (from `calc_pv`), a heartbeat writer, and failure-drill tests.
- Hardware addresses and FINS settings go in configuration, not in driver code.

### 10.10 Open questions

- [ ] Safe RPM value; heartbeat and comms-loss timeouts.
- [ ] Behaviour if the PLC itself fails.
- [ ] Pi-to-PLC protocol (FINS/TCP is the candidate) and the PLC memory map for counts, flow, heartbeat, setpoint.
- [ ] ACS560 comms-loss values (safe frequency, timeout). The parameters and the default register map are now known (`connection-diagram.md` §5.2); the installed drive's settings are not.
- [ ] How the speed leaves the PLC today, and exactly what the HMI writes to the drive today.
- [ ] PLC PID constants and form (PIDAT, §12.7).
- [ ] Flow word scaling and table grid.
- [ ] Ambient temperature sensor use (logging, compensation, feed-forward).
- [ ] Which network the Pi joins.
- [ ] Restart rules after a power cut.
- [ ] Drive fault handling and restart.

## 11. Instrument and Control-Unit Data (from vendor documents)

Added 2026-11-14 from the owner's Google Drive folder of vendor manuals. Copies of the files
that could be fetched are in `project/reference-docs/` (see §11.6). Facts below are quoted
from those documents; anything marked **(verify)** is inference. Sections 11.1–11.4 describe
parts that **stay in service**; they matter for the PLC program and for understanding the
existing scaling.

### 11.1 Temperature transmitter: Novus TxRail-USB (V2.0x)

| Item | Value |
|---|---|
| Mounting / power | 35 mm DIN rail; 2-wire loop powered, 10–30 V DC (12–30 V for the 0–10 V output) |
| Inputs | Pt100, Pt1000 (3-wire; 2-wire by linking terminals), NTC 10 kΩ, thermocouples J K T E N R S B, 0–50 mV, 0–100 mV |
| Output | 4–20 mA (or 20–4), or 0–10 V (or 10–0), software selectable; 2 µA / 0.0025 V resolution |
| Max loop load | `RL = (Vdc − 10) / 0.02` Ω (e.g. 700 Ω at 24 V) |
| Accuracy | Pt100/Pt1000 0.10–0.19 % **of the sensor's maximum range** (not the programmed span), e.g. up to about ±1.6 °C for Pt100 at 500–600 °C; thermocouples 0.1–0.15 % plus < ±1 °C cold-junction error |
| Response / warm-up | 1.6 s typical; switch-on delay < 2.5 s; accuracy guaranteed only after 15 min |
| Sensor-failure output | Configurable: downscale (< 3.8 mA / 0 V) or upscale (> 20.5 mA / 10 V). Factory default is upscale |
| Factory configuration | Pt100 3-wire, 0–100 °C, 4–20 mA. Our `t_eng_min/max = 0..250` implies it was re-ranged **(verify)** |
| Configuration | USB (Micro-USB) with SigNow or TxConfig II (PC) or the SigNow Android app (OTG). Settings: sensor type, lower/upper range limit, failure behaviour, output type, zero offset |
| Isolation | **None** between input, output and the USB port. Do not configure with the sensor connected to the process |
| Environment | −40 to 85 °C, 0–90 % RH; CE, UKCA |

From the owner's deck (§12.1): the sensor is an **RTD (Pt100 or Pt1000) wired 3-wire** to
terminals 1, 3 and 4, and the wiring drawing shows the **0–10 V output** variant (output on
terminals 5/6 and 7/8, supply 12–30 V). If that is how it is actually wired, the temperature
reaches the PLC as 0–10 V on an AD041 voltage input, not as 4–20 mA **(verify on site)**.

Design implications (rewritten 2026-11-16; the earlier text assumed an ADC on the Pi, which
§10 dropped):

- **A failed transmitter does not produce the `8000` code.** Upscale failure (above 20.5 mA,
  the factory default) converts to about 6190 counts and downscale (below 3.8 mA) to about −75
  counts; `8000` appears only below 3.2 mA (§11.3). Fault detection in the PLC needs count-band
  checks in addition to the `8000` test, matched to the configured failure direction.
- On the **0–10 V** output a failure gives 0 V or 10 V, which are valid readings, and the
  AD041 has no open-circuit detection on that range (§12.2). Using the 4–20 mA output gives
  real wire-break detection.
- The same transmitter family could serve the **ambient** temperature input (Pt100 or NTC).

### 11.2 Pressure transmitters (P1, P2)

Not in the vendor folder. Model, range and output signal are still unknown. The legacy scaling
(`p1_plc_min/max = 0..6000` raw, `-250..250` engineering) suggests a 4–20 mA signal on a
CP1W-AD041 input, but that is inferred **(verify)**. The transmitter model and range are
needed to set `eng_min/max` and the fault bands. (No ADC is needed on the Pi, §10.)

### 11.3 Legacy PLC analog I/O (Omron CP1W expansion units, CP2E base)

| Unit | Specification |
|---|---|
| CP1W-AD041 (analog input) | 4 inputs. Voltage 0–5, 1–5, 0–10, ±10 V (input impedance ≥ 1 MΩ) or current 0–20 / 4–20 mA (about 250 Ω). Resolution 1/6000. Data 0000–1770 hex (**0–6000**). Accuracy 0.3 % FS (voltage) / 0.4 % FS (current) at 25 °C, doubling over 0–55 °C. Conversion 2 ms/point (8 ms for all 4). Averaging and open-circuit detection supported. Photocoupler isolation from the PLC, none between channels |
| CP1W-DA041 (analog output) | 4 outputs. 1–5, 0–10, ±10 V (load ≥ 2 kΩ) or 0–20 / 4–20 mA (load ≤ 350 Ω). Resolution 1/6000, 0–6000 counts. Accuracy 0.4 % FS at 25 °C. 2 ms/point |
| CP1W-MAD11, CP1W-TS001/101/002/102 | Mixed analog I/O and temperature (RTD/thermocouple) units listed in the same manual. Not read in detail |
| Expansion limit | Up to 3 expansion units on a 30/40/60-point CPU. Confirmed for the CP2E-N30 in W613 (2026-11-16). Expansion words follow the CPU's: inputs from CIO 2, outputs from CIO 102 (W614) |

- The full-scale value of **6000 counts** confirms the `*_plc_min/max = 0..6000` defaults. The
  Pi reads these counts from the PLC, and the golden-test data from the old system is in them.
- After power-up the unit reports `0000` for two scans plus about 50 ms, and converts nothing
  until the range codes have been written.
- **Confirmed (owner's deck, §12.2):** with open-circuit detection active, the converted data
  becomes **8000** (4–20 mA input below 3.2 mA). This is the origin of `plc_ai_error = 8000`.
- **Negative counts are legitimate.** The AD041 converts −300 to 6300 (hex FED4 to 189C).
  A 4–20 mA signal between 3.2 and 4 mA gives −300…0 as a two's-complement 16-bit value; a
  0–10 V input gives negative counts down to −0.5 V. So the old `# todo: detect and handle
  negative values` in `plc.py` is about two's complement, not an error: values above 0x7FFF
  must be sign-converted, then 8000 treated as the fault code.
- Range selection and averaging are set per input in output words n+1 and n+2: range code 00 =
  −10…10 V, 01 = 0…10 V, 10 = 1…5 V or 4…20 mA, 11 = 0…5 V or 0…20 mA, plus averaging and
  input-use bits. Which range each channel uses is unknown **(verify in the PLC program)**.
- Which expansion unit is actually fitted is still unknown. The deck's AD041 pages suggest
  the CP1W-AD041 is the unit in use.
- Other units in the same manual: CP1W-MAD11 (2 analog in + 1 analog out, 1/6000, out load
  600 Ω max for current), CP1W-TS101/TS102 (Pt100/JPt100, ±0.5 % or ±1 °C, 250 ms
  conversion), CP1W-TS001/TS002 (thermocouples K/J).

### 11.4 Legacy drive and HMI

**ABB ACS560 (firmware and hardware manuals now in `reference-docs/`; searched 2026-11-16 for
the facts below, not read cover to cover)**

- The ACS560-01-12A6-4 is frame **R1** (12.6 A, 5.5 kW).
- Built-in **Modbus RTU (EIA-485)** on terminal block X5: B+ (29), A− (30), DGND (31). Frames
  R0–R2, so this drive, have **one** combined switch `S100 TERM & BIAS` (default off); the
  separate S100 termination and S200 bias switches are on frames R3–R8.
- Embedded fieldbus, group 58: 58.01 enables Modbus RTU, 58.03 node address, 58.04/58.05 baud
  and parity, **58.14 communication loss action (default Fault, i.e. the drive trips)**, 58.15
  loss mode (default: only control-word or reference writes reset the timer), 58.16 loss time
  (default 3.0 s). Safe reference is 28.41 (frequency) or 22.41 (speed). Default registers:
  400001 control word, 400002 reference 1, 400004 status word. Details in
  `connection-diagram.md` §5.2.
- DI5 can be configured as a frequency input (0–16 kHz, group 11).
- The STO terminal numbers differ between the default-connection table (deck slide 7) and the
  hardware manual's technical data; read the labels on the drive.
- Two external control locations (EXT1/EXT2); start/stop and reference can come from I/O or
  fieldbus. Parameter 49.05 sets the reaction to a panel/PC-tool comms break (not to fieldbus).
- Hardwired **Safe Torque Off** on X4; three relay outputs (Ready, Running, Fault); two
  analog inputs (AI1 voltage or current, AI2 current at 100 Ω); 24 V auxiliary output
  (max 250 mA); 24 V AC/DC control-unit supply input on R6–R8 frames only.
- Has built-in **external PID** (group 71), usable as a drive-side fallback loop **(verify)**.

**Weintek cMT3072XH2 HMI**

- 7" 1024×600, 24 V DC (±20 %, 820 mA), IP66 front, 0–55 °C, 2× Ethernet, RS-485 (COM2/COM3),
  RS-232, CAN, USB host. EasyBuilder Pro V6.07.01 or later.
- Talked to the PLC via Omron FINS/TCP, port 9600, PLC station 0, tags imported from CX-Programmer
  `.cxr` exports. Addresses used are DM/CIO/W/H/A/T/C areas.
- Its operating range (0–55 °C) and 24 V supply are relevant if the same enclosure is reused.

### 11.5 New control unit: Raspberry Pi 5 Compute Module

Not from the vendor folder; general knowledge, to be verified against the chosen carrier board.
Under the architecture in §10 the Pi is a supervisor on the PLC's Ethernet network, so its
requirements are small.

- The CM5 module itself has no analog inputs and no RS-485. **Neither is needed**: sensors stay
  on the PLC and the Pi never talks to the drive.
- Carrier board requirements: Ethernet, 24 V DC input (or a clean 5 V supply from the cabinet),
  RTC with battery, hardware watchdog, DIN-rail mounting, industrial temperature range for the
  kiln room, eMMC or NVMe (SQLite WAL logging wears SD cards), and a display output for the
  kiosk monitor.
- Choose the carrier from this list; buy once a board meets it. All Python code is
  hardware-independent and is built against simulated drivers first.
- The Pi reads and writes PLC memory over FINS (the `fins` package already in `requirements.txt`).
  Checked 2026-11-16 against the installed `fins` 1.0.5: the calls are `memory_area_read` and
  `memory_area_write`; the library negotiates FINS node addresses itself, leaves the socket
  without a timeout after connecting, and also exposes calls that stop the PLC or write its
  program, which the Pi code must never use (`connection-diagram.md` §8).

### 11.6 Reference documents

Stored in `project/reference-docs/` (fetched 2026-11-14 from the owner's Drive folder):

| File | Content |
|---|---|
| `manual_txrail_usb_transmitter_4-20ma_v20x_g_en.pdf` | Novus TxRail-USB user manual |
| `txrail-usb.criptografado_v200.zip` | TxRail-USB configuration package (encrypted/obfuscated, not inspected) |
| `CP1W-AD_DA_MAD_TS_DRT_SRT Pages from W471-E1-04.pdf` | Omron CP1W analog / temperature / link unit pages |
| `w483_cp1e_cp2e_cpu_unit_instructions_reference_manual_en.pdf` | Omron CP1E/CP2E instruction reference |
| `cMT3072XH2_Datasheet_ENG_20240619.pdf`, `GMEC72X2N_cMT3072X2_XH2_Installation_20240619.pdf` | Weintek HMI datasheet and installation guide |
| `HMI PLC Connection Guide OMRON_CJ_CS_CP_Ethernet_FINS_TCP.pdf` | HMI-to-PLC FINS/TCP setup |
| `Chapter-43-JS-Object-and-JS-Library-UserManual-eng.pdf` | Weintek JS object/library manual |

The owner's own annotated deck is `docs/Kiln CS Fan PID.pdf` (8 slides, see §12).

**How much of each document was actually read (2026-11-14):**

| Document | Read |
|---|---|
| `docs/Kiln CS Fan PID.pdf` | All 8 pages (slide images viewed; page 8 is blank) |
| TxRail-USB manual, HMI datasheet, HMI install guide, HMI–PLC guide | Full text |
| CP1W unit pages (70 pages) | Text searched for AD/DA/MAD/TS specs; not read cover to cover |
| CP1E/CP2E instruction reference (530 pages) | Text searched: PIDAT, SCL, PWM, SPED, instruction list; not cover to cover |
| CP2E hardware and software manuals | Text searched through the Drive reader for model, ports and Modbus/PID sections; not cover to cover. The N30DT1-D is a **sourcing (PNP) transistor output** model on 24 V DC; N-type has built-in Ethernet and takes up to 2 serial option boards |
| ACS560 quick-start guide | Text searched (default ABB standard macro I/O, no Modbus register data) |
| ACS560 firmware manual | About the first 236k characters only; the embedded-fieldbus (Modbus) chapter was **not reached** |
| ACS560 hardware manual (83 MB) | **Not read**: the Drive text reader returned empty content |
| Weintek JS chapter | First pages only (JS object overview; EasyBuilder Pro V6.10.01, ECMAScript 2017) |
| SigNow installer, TxRail config zip | Not inspected |

**Added 2026-11-16 from the manufacturers' sites** (full list with sources in
`connection-diagram.md` §11): `w613_cp2e_hardware_users_manual_en.pdf`,
`w614_cp2e_software_users_manual_en.pdf`, `w342_fins_commands_reference.pdf`,
`p150_cp1e_to_cp2e_replacement_guide_en.pdf`, `ACS560_firmware_manual_IGPKA216x_en.pdf`,
`ACS560_hardware_manual_3AXD50000044998_en.pdf` (83 MB), `cMT3072XH_datasheet_wachendorff.pdf`.
These were searched for specific facts, not read cover to cover. The "how much was read" table
above describes the 2026-11-14 state.

**Still only in the owner's Drive folder:** `EN_ACS560_QISG_K.pdf` (quick guide) and
`signowsetupv11900.zip` (SigNow installer).

### 11.7 New open questions from this review

- [ ] Probe type and programmed range of the TxRail-USB (and whether its sensor-failure
  direction is upscale or downscale).
- [ ] Model, range and output signal of the P1/P2 pressure transmitters.
- [ ] Which CP1W expansion units are fitted today (needed to read the old data scaling).
- [ ] ACS560 Modbus register map, comms-loss parameters and fieldbus control profile
  (firmware manual chapter "Fieldbus control through the embedded fieldbus interface").
- [x] Whether the ACS560 is retained or replaced: it stays (decided 2026-11-14, §10).
- [ ] CM5 carrier board: Ethernet, 24 V input, RTC, hardware watchdog, DIN rail, eMMC/NVMe,
  display output. No ADC or RS-485 needed (§10, §11.5).
- [ ] Ambient temperature sensor type and where it is mounted.

## 12. Owner's "Kiln CS Fan PID" Deck: How the Existing System Is Wired

> Written before the §10 architecture was agreed. The wiring facts hold. The design
> consequences in §12.8 that assume a Pi-based replacement are superseded by §10.

Source: `docs/Kiln CS Fan PID.pdf` (8 slides, read 2026-11-14). The slides combine vendor
extracts with the owner's hand sketches. Facts taken directly from printed text are stated
plainly; readings of the hand-drawn sketch are marked **(interpretation)**.

### 12.1 Slide 1: temperature transmitter wiring

TxRail-USB, Pt100/Pt1000 **3-wire** RTD on terminals 1, 3, 4. The drawing shows the **0–10 V
output** wiring (output terminals 5/6 and 7/8, load across 7/8), with the supply note
"10–30 V for 4–20 mA, 12–30 V for 0–10 V". Whether the site actually uses the voltage or the
current output is **(verify)**. See §11.1.

### 12.2 Slide 2: analog input unit (CP1W-AD041)

- Terminal layout: V IN1…4, I IN1…4, COM1…4 (for a current input the V IN and I IN terminals are linked,
  per the wiring figures). Shielded twisted pair, shield to FG.
- Accuracy table incl. extended ranges: current 0.4 % FS at 25 °C, 0.8 % at 0–55 °C, 0.8 %
  at 55–60 °C, 1 % at −20–0 °C.
- 4–20 mA: 0–6000 counts, convertible range −300…6300 (FED4…189C hex, two's complement below
  4 mA). **Below 3.2 mA the open-circuit function sets the data to 8000.** 0–10 V: same counts,
  −0.5 V…10.5 V. **Corrected 2026-11-16:** the 0–10 V range has **no** open-circuit detection.
  The manual limits it to the 1–5 V range (below 0.8 V) and the 4–20 mA range (below 3.2 mA);
  the "8,000" caption under the 0–10 V graph on the slide is a general note. A broken wire on a
  0–10 V input reads near 0 V, or about 1/3 to 1/2 of another channel's voltage when the
  transmitters share a supply.
- Set-data words n+1/n+2 (bit 15 = 1 to apply) hold per-input range code, averaging and
  input-use bits.

### 12.3 Slides 3 and 4: PLC outputs

- CP2E-N30DT1-D built-in **pulse outputs**: 4 outputs on **CIO 100.00, 100.01, 101.00, 101.01**,
  1 Hz–100 kHz, pulse + direction, continuous (speed) or independent (position) mode, with
  trapezoidal acceleration. **PWM** output: 2–6553.5 Hz in 0.1 Hz steps (or 2–32000 Hz in 1 Hz
  steps with one output), duty 0–100 % in 0.1 % steps.
- Terminal layout: inputs on CIO 0.00–0.11 and CIO 1.00–1.05 (18 inputs), outputs on CIO
  100.00–100.07 and CIO 101.00–101.03 (12 outputs). The `DT1` suffix means sourcing (PNP)
  transistor outputs (24 V DC supply).
- **Why this matters:** the CP2E base unit has no analog output. The owner's focus on pulse and
  PWM outputs suggests the fan speed reference may leave the PLC as **PWM/pulse** rather than as
  an analog voltage **(verify; a CP1W-DA041 or analog option board would be the alternative)**.
  Any PWM-to-analog conversion would sit between the PLC and drive terminal AI1.

### 12.4 Slide 5: hand sketch of the architecture and the control path **(interpretation)**

- **Links:** HMI to ACS560 over **RS-485 Modbus**, labelled "status", so the HMI reads drive
  status directly. HMI to PLC over **Ethernet** (labelled "Modbus / Hostlink"; the connection
  guide in the folder says Omron FINS/TCP, so the label is probably shorthand). Three sensor
  signals go into the PLC. The PLC sends a speed signal to the drive. The drive drives the fan
  motor, with a chimney sketched beside it.
- **Control path:** `SV` (setpoint) and `PV` go into an error block `e`, then `PID`, then a
  selector. `PV` is derived from P1, P2 and T (the flow calculation). The selector chooses
  between **`min_RPM`**, the **PID output** and **`man_RPM`**, and the result is the control
  signal `CS` sent on to the drive. This matches `FanDrive`/`Command` in `fan-ctrl` (PID and
  MAN modes, clamped to motor limits). It also suggests a minimum-speed state, which in the
  Python code is `motor_min_rpm`/`pid_min_rpm` **(verify how the PLC picks `min_RPM`)**.
- A duct/stack profile sketch (not interpreted).

### 12.5 Slide 6: network and RS-485 wiring (printed)

| Device | Port | Address / pin |
|---|---|---|
| Weintek cMT3072XH | LAN 1 | 192.168.16.19 (plant network) |
| Weintek cMT3072XH | LAN 2 | 192.168.100.1 (direct link to the PLC) |
| Omron CP2E-N30DT1-D | Ethernet port A | 192.168.100.7 |
| Weintek CON A (D-sub 9 female) | Pin 1 Data−, pin 2 Data+, pin 5 GND | to ACS560 X5: **30 A−, 29 B+, 31 DGND** |

- The PLC and HMI sit on a private 192.168.100.x link; the HMI also reaches the plant LAN on
  192.168.16.x. The Pi design must decide which network the new controller joins.
- **The HMI is wired straight to the ACS560 over Modbus RTU.** The deck labels it "status", but
  nothing in the hardware stops the HMI from writing drive control words too. This is a second
  possible control path next to the PLC speed signal (the conflict risk in §5). Under §10 the
  PLC owns the PID and the demanded RPM, the HMI is the only Modbus master on the drive, and
  the Pi never writes to the drive.
- The datasheet in `reference-docs/` is for the cMT3072XH2 while the deck names the cMT3072XH;
  confirm the fitted model on its nameplate **(verify)**.

### 12.6 Slide 7: ACS560 default I/O (ABB standard macro)

Printed terminal table, same as the quick-start guide: X1 AI1 external frequency reference
0–10 V (par. 22.11), AI2 not configured, AO1 output frequency, AO2 output current; X2/X3 DI1
stop/start (20.03), DI2 forward/reverse, DI3/DI4 constant-frequency selection, DI5 ramp
selection; relays RO1 Ready run, RO2 Running, RO3 Fault; X5 built-in Modbus RTU (B+, A−,
DGND) with termination (S100) and bias (S200) switches; X4 Safe Torque Off (both circuits
closed to run); X11 +24 V auxiliary output (250 mA max). This is the **factory default**; the
parameters actually set on the installed drive are unknown **(verify with a parameter
backup from the drive)**.

### 12.7 PLC PID instruction (from the CP1E/CP2E instruction reference)

If the old PID runs in the PLC, the likely instruction is **PIDAT(191)**: PID with autotuning.
It has more features than `fan-ctrl/pid.py`, so the cutover behaviour will differ unless
matched:

- Two-degree-of-freedom PID with a target-value filter (parameter α), not the textbook form.
- Autotuning by the limit-cycle method (stores P, I, D automatically; command bit C+9 bit 15).
- Parameters: SV, proportional **band** (not gain), integral time, derivative time, sampling
  period (10 ms units, 0.01–99.99 s), forward/reverse action, output limits, input/output
  bit range (e.g. 12 bit = 0–0FFF), and an optional 0 % or 50 % output at PV = SV.
- Bumpless transfer is **not** done on start; limit flags show when output hits the limits.
- Related scaling and averaging instructions exist (SCL, SCL2, SCL3, AVG) that may sit
  between the AD041 counts and the flow calculation in the PLC program.

The real constants and the PLC program itself are only in the CX-Programmer project.

### 12.8 What this changes for the design

- `plc_ai_error = 8000` and the `0–6000` scaling are now confirmed (§11.3).
- Sensor fault detection is per-signal and lives in the PLC (§10.5): current out of its valid
  band (below 3.2 mA is the existing detection threshold; the TxRail fail-safe is below 3.8 mA
  or above 20.5 mA), or a voltage equivalent if the 0–10 V output is used.
- The PLC PID is kept (§10.2). If it is ever ported to the Pi for simulation or later use,
  record the old proportional band, integral and derivative times, sampling period,
  forward/reverse sense and limits, because `pid.py` uses gains and a different form.
- The HMI-to-drive Modbus link means the drive already works over RS-485 Modbus RTU. Under §10
  the HMI stays the single Modbus master and the Pi never talks to the drive.

### 12.9 New open questions from the deck

- [ ] How the PLC sends the speed reference to the drive (PWM/pulse, a CP1W-DA041, or other)
  and what it is wired to on the drive (AI1 or Modbus).
- [ ] Whether the HMI ever writes to the drive over RS-485 (control words) or only reads status.
- [ ] Drive parameter backup: which macro and which parameters are set; comms-loss settings.
- [ ] CX-Programmer project (`.cxp`) and Weintek project (`.cmtp`): DM map, PIDAT constants,
  scaling, how `min_RPM` is chosen.
- [ ] Which network the Pi joins (192.168.100.x link or 192.168.16.x plant LAN).
