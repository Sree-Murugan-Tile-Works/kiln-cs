# Field Hardware Overview

This document captures the real field hardware behind `kiln-cs`, as described by the
project owner, and maps each physical device/sensor onto the existing `fan-ctrl`/`dashboard`
code. Items that are inferred rather than directly confirmed are marked **(verify)**.

## 1. Application

The system controls combustion-air / draft fan speed on a **Hoffman-type continuous kiln**,
regulating the flow of exhaust gas leaving the kiln by varying fan RPM in response to a
flow measurement taken across an orifice plate.

## 2. Hardware Inventory

| Component | Model | Role |
|---|---|---|
| HMI | Weintek cMT3072XH | Local operator touch panel — independent of the `dashboard/` Flask app, talks to the PLC directly |
| PLC | Omron CP2E-N30DT1-D | Field I/O concentrator; reads P1/P2/T sensors, drives the fan reference; the only thing `fan-ctrl/plc.py` talks to |
| Fan drive | ABB ACS560-01-12A6-4 | VFD that actually spins the combustion-air fan motor at the commanded RPM |
| Flow element | Orifice plate | Fixed restriction in the duct; the pressure drop it creates is the basis for the flow calculation in `calculation.calc_pv` |
| Pressure transmitter 1 (P1) | unspecified **(verify)** | High side connected **upstream** of the orifice plate; low side vented to room/atmospheric pressure |
| Pressure transmitter 2 (P2) | unspecified **(verify)** | High side connected **downstream** of the orifice plate; low side also vented to room/atmospheric pressure |
| Temperature sensor | unspecified **(verify)** | Measures gas temperature at/near the orifice plate; feeds `T` in the flow equation |

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

## 4. PLC ↔ Python Link (`fan-ctrl/plc.py`)

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

## 5. HMI Relationship to This Codebase

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

## 6. PLC ↔ Drive Link (Omron CP2E ↔ ABB ACS560)

**(verify — not yet decided)** The ACS560 needs a speed/frequency reference from somewhere.
Typical options for this drive family:

- **Analog reference** (0–10V or 4–20mA) from a PLC analog output module.
- **Modbus RTU** over RS-485, using the ACS560's embedded fieldbus interface and the CP2E's
  serial port (if present) as Modbus master.
- An optional ABB fieldbus adapter module (Profibus/Ethernet) on the drive, if fitted.

Today, `fan_drive.FanDrive.commanded_rpm` is computed in Python and handed to
`KilnPLC.write()`, which just notes a `DM_MOTOR_RPM` register placeholder and does nothing
real yet. Once the comms method to the ACS560 is decided, `write()`/`write_dm()` need to
encode `commanded_rpm` into whatever the PLC then forwards to the drive (a raw DM value for
an analog output channel, or a value the PLC's ladder logic relays over Modbus).

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
