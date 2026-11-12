# TODO

## In Progress

## Done
- [x] Add Claude Code support files (`CLAUDE.md`, `CLAUDE-COMMON.md`, `PROJ_STARTER.md`, `.claude/skills/`) — bootstrapped from the `kl-mithunvel/claude` template repo
- [x] Document real field hardware (HMI/PLC/drive/sensors) and the orifice-plate formula mapping in `project/hardware-overview.md`; updated `CLAUDE.md` Platform Constraints/Deployment Notes accordingly

## Not Started
- [ ] **New control system (Pi + new HMI + new VFD):** define the sensor-input and drive-output interfaces that replace `fan-ctrl/plc.py` (see `project/hardware-overview.md` §10)
- [ ] Build simulated sensor and drive drivers with the same interface/data shape, so the control loop runs and tests on the dev machine
- [ ] Choose how the Pi reads the sensors (ADC/HAT 4–20 mA vs Modbus transmitters) and record transmitter signals/ranges
- [ ] Choose the VFD model and the Pi-to-VFD command path (Modbus RTU recommended if supported)
- [ ] Choose the HMI model and connection; keep the Pi as the single control authority
- [ ] Design watchdog and fail-safe behaviour: VFD comms-loss action, hardwired E-stop, defined fan state on Pi reboot, manual bypass
- [ ] Agree the cutover plan (parallel run vs hard switch); log the old system alongside if possible for `calc_pv` golden-test data
- [ ] Move hardware addresses/ports/serial settings into YAML config (not driver code)
- [ ] Gather any old-system records (original equation/constants, logged P1/P2/T/Q data) and confirm whether the `calculation.py` `__main__` example is a real operating point
- [ ] Add golden/characterisation tests for `calc_pv` pinning current behaviour before any change (see `project/process-description.md` §3)
- [ ] Answer the open process questions in `project/process-description.md` §8 (plate/fan position, ranges, what the "control system change" covers, ambient T usage)
- [ ] Write a plan in `project/` for the visual GUI-based process simulation (kiln, duct, plate, fan, chimney, natural draft) for team review before implementing
- [ ] Decide how the ambient temperature sensor is used (logging, compensation, feed-forward) and add an `ambient_t` input if needed
- [ ] Flag stuck/implausible pressure readings (tar/condensate fouling of impulse lines) in `plc.py`/`main.py`
- [ ] ~~Wire up real `fins.tcp` reads/writes in `fan-ctrl/plc.py`~~ — SUPERSEDED 2026-11-13: the Omron PLC is being replaced by a Pi-based system (see the new control system tasks above)
- [x] Fix `fan-ctrl/pid.py: PIDController.set_cfg` — `ki`/`kd` are never read from config (only `kp` is set, three times) — fixed, added `__main__` test block
- [ ] Handle negative analog-input values in `fan-ctrl/plc.py: read_all` (existing `# todo` in source) — carry over to the new sensor-input driver; suction gives negative gauge readings
- [x] Remove leftover debug `print()` calls in `dashboard/web.py` — removed in dashboard rewrite
- [x] Add a `pytest` test suite for `fan-ctrl` and `dashboard` — 60 tests across fan_ctrl (utils, calculation, pid, command, fan_drive, config, dbwriter) and dashboard (all API routes + coerce_for_type)
- [x] Create shared `requirements.txt` (project root, UTF-8) covering both fan-ctrl and dashboard packages; add `setup.bash` for one-command Pi bootstrap
- [ ] Wire `fan-ctrl/main.py` to call `dbwriter.log_error()` on PLC comm failures and other runtime errors
- [ ] Document a deployment target and fill in `CLAUDE.md`'s Deployment Notes section
- [ ] Decide and implement the PLC↔ACS560 drive command path (analog setpoint vs. Modbus) for `plc.py`/`fan_drive.py` (see `project/hardware-overview.md` §6)
- [ ] Confirm the CP2E-N30DT1-D has (or will get) the analog I/O module(s) needed for the 2 pressure transmitters + temperature sensor (see `project/hardware-overview.md` §4)
- [ ] Verify whether `calc_pv` should use absolute or gauge P1/P2 (sensors are gauge, vented to atmosphere) and whether `T` should be Celsius or Kelvin (see `project/hardware-overview.md` §7)
