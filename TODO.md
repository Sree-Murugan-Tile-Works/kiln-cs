# TODO

## In Progress

## Done
- [x] Add Claude Code support files (`CLAUDE.md`, `CLAUDE-COMMON.md`, `PROJ_STARTER.md`, `.claude/skills/`) — bootstrapped from the `kl-mithunvel/claude` template repo
- [x] Document real field hardware (HMI/PLC/drive/sensors) and the orifice-plate formula mapping in `project/hardware-overview.md`; updated `CLAUDE.md` Platform Constraints/Deployment Notes accordingly

- [x] Extend `project/hardware-overview.md` with vendor-document data (new §11: TxRail-USB, CP1W analog units, ACS560/HMI facts, CM5 notes) and copy 8 reference files into `project/reference-docs/` (2026-11-14)
- [x] Read the owner's `docs/Kiln CS Fan PID.pdf` and the reachable vendor PDFs; add §12 (legacy wiring, network, PLC outputs, PIDAT) and corrections to §11 in `project/hardware-overview.md` (2026-11-14)
- [x] Agree the control architecture with the owner (PLC, HMI and ACS560 stay; Pi added as supervisor; lookup-table fallback; hardwired run/stop and E-stop) and rewrite `project/hardware-overview.md` §10, with matching updates to `.claude/CLAUDE.md`, `project/process-description.md` and `project/implementation-plan.md` (2026-11-14)
- [x] Process simulation physics core `sim/` (parameter registry with slider metadata, natural draft/chimney/orifice plate/fan model, instruments with PLC counts and faults, closed loop on the real `PIDController`/`FanDrive`/`Command`/`Scaler`) with 131 tests in `tests/sim/` (2026-11-14)
- [x] Process simulation GUI `sim/server.py` + `sim/static/` (Flask, vanilla JS): 45 sliders built from the parameter registry, PID/manual/off, sensor faults and drift, live schematic and four charts; run with `python -m sim.server` then open http://127.0.0.1:5002; 142 sim tests, full suite 266 passed (2026-11-14)
- [x] Publish a shareable approval page (who drives what, connections, fail-safe plan, execution plan) — https://claude.ai/artifact/QTxBwFJL4baTap6qoHf4Ba (2026-11-14)

## Not Started
- [ ] Get the CX-Programmer project (`.cxp`) and Weintek project (`.cmtp`) from the site: DM map, PIDAT constants (P band, Ti, Td, sampling period, forward/reverse, limits), scaling, how `min_RPM` is chosen, how the speed reference leaves the PLC
- [ ] Get a parameter backup from the installed ACS560 (macro, comms-loss action, reference source) and confirm whether the HMI writes drive control words over RS-485
- [ ] After the simulation, decide whether the Python PID (simulation only) must match the PLC's PIDAT behaviour (2-DOF PID with proportional band); note differences in `project/hardware-overview.md` §12.7
- [ ] Download the 6 reference files over 10 MB manually from the Drive folder (ACS560 firmware/HW/QISG, CP2E HW/SW manuals, SigNow installer) into `project/reference-docs/`, then read the ACS560 Modbus register map and comms-loss parameters
- [ ] Decide whether `project/reference-docs/` is committed, git-ignored, or moved to Git LFS (about 9 MB of PDFs now)
- [ ] Resolve the open questions in `project/hardware-overview.md` §10.10 and §11.7 (safe RPM and timeouts, PLC-failure behaviour, TxRail probe/range, CM5 carrier board)
- [ ] **Get team approval** of the architecture in `project/hardware-overview.md` §10 (approval page: https://claude.ai/artifact/QTxBwFJL4baTap6qoHf4Ba, private until shared); then regenerate `project/implementation-plan.md` phases from §10.8–§10.9
- [ ] **Pi supervisor architecture (2026-11-14):** Pi reads PLC counts over FINS, runs `calc_pv`, writes flow plus a heartbeat to the PLC; PLC runs the PID; HMI bridges the demanded RPM to the ACS560 over Modbus (see `project/hardware-overview.md` §10)
- [ ] Build a simulated PLC link and a simulated drive with the same interface/data shape as the real ones, so the loop and the failure drills run on the dev machine
- [ ] Write the fallback table generator: 2-D flow table over (P2/P1, T) from the unchanged `calc_pv`, with the PLC-side integer scaling, grid and edge behaviour, plus interpolation tests
- [ ] Define the Pi-to-PLC memory map (counts, flow, heartbeat, setpoint, demanded RPM, status) and the heartbeat timeout/return rule; confirm FINS/TCP on the CP2E Ethernet port
- [ ] PLC program changes (flow source selector, heartbeat watch, table lookup, safe-RPM handling): specify them for the PLC programmer; they are not Python work
- [ ] Decide what the fan does if the PLC itself fails (e.g. HMI writes the safe speed when the demanded RPM goes stale)
- [ ] Set the ACS560 comms-loss action and the safe RPM; read the firmware manual's embedded-fieldbus chapter first
- [ ] Define the numeric safe RPM, the heartbeat timeout and the comms-loss timeout with the process owner
- [ ] Write failure-drill procedures for each row of `project/hardware-overview.md` §10.5 (unplug the Pi, disconnect RS-485, sensor fault, table out of range)
- [ ] Choose the CM5 carrier board against the requirements in `project/hardware-overview.md` §11.5 (Ethernet, 24 V, RTC, watchdog, DIN rail, eMMC/NVMe, display)
- [ ] Log first: Pi reads and logs flow in parallel while the PLC controls, to compare and to capture golden-test data for `calc_pv`
- [ ] Move hardware addresses/ports/serial settings into YAML config (not driver code)
- [ ] Gather any old-system records (original equation/constants, logged P1/P2/T/Q data) and confirm whether the `calculation.py` `__main__` example is a real operating point
- [ ] Add golden/characterisation tests for `calc_pv` pinning current behaviour before any change (see `project/process-description.md` §3)
- [ ] Answer the open process questions in `project/process-description.md` §8 (plate/fan position, ranges, what the "control system change" covers, ambient T usage)
- [x] ~~Write a plan in `project/` for the simulation~~ — owner gave direction in chat and asked for implementation directly (physics core first, then GUI); design notes are in the `sim/plant.py` docstring
- [ ] Decide how the ambient temperature sensor is used (logging, compensation, feed-forward) and add an `ambient_t` input if needed
- [ ] Flag stuck/implausible pressure readings (tar/condensate fouling of impulse lines) in `plc.py`/`main.py`
- [ ] Wire up real `fins.tcp` reads/writes in `fan-ctrl/plc.py` — REINSTATED 2026-11-14: the PLC stays, so this is the Pi-to-PLC link. The 2026-11-13 "superseded" note is withdrawn. The write path now carries flow plus heartbeat instead of a commanded RPM (see `project/hardware-overview.md` §10.9)
- [x] Fix `fan-ctrl/pid.py: PIDController.set_cfg` — `ki`/`kd` are never read from config (only `kp` is set, three times) — fixed, added `__main__` test block
- [ ] Handle negative analog-input values in `fan-ctrl/plc.py: read_all` (existing `# todo` in source) — counts are two's complement (−300…6300) and 8000 is the open-circuit code (`project/hardware-overview.md` §11.3); handle both in the Pi-side PLC reader; suction gives negative gauge readings
- [x] Remove leftover debug `print()` calls in `dashboard/web.py` — removed in dashboard rewrite
- [x] Add a `pytest` test suite for `fan-ctrl` and `dashboard` — 60 tests across fan_ctrl (utils, calculation, pid, command, fan_drive, config, dbwriter) and dashboard (all API routes + coerce_for_type)
- [x] Create shared `requirements.txt` (project root, UTF-8) covering both fan-ctrl and dashboard packages; add `setup.bash` for one-command Pi bootstrap
- [ ] Wire `fan-ctrl/main.py` to call `dbwriter.log_error()` on PLC comm failures and other runtime errors
- [ ] Document a deployment target and fill in `CLAUDE.md`'s Deployment Notes section
- [ ] Decide and implement the PLC↔ACS560 drive command path (analog setpoint vs. Modbus) for `plc.py`/`fan_drive.py` (see `project/hardware-overview.md` §6)
- [ ] Confirm the CP2E-N30DT1-D has (or will get) the analog I/O module(s) needed for the 2 pressure transmitters + temperature sensor (see `project/hardware-overview.md` §4)
- [ ] Verify whether `calc_pv` should use absolute or gauge P1/P2 (sensors are gauge, vented to atmosphere) and whether `T` should be Celsius or Kelvin (see `project/hardware-overview.md` §7)
- [ ] Simulation follow-ups: run the legacy `calc_pv` in the sim loop once its input units are known (currently a clean orifice-equation estimate is used), simulated PLC/drive twins with the Pi-to-PLC memory map, heartbeat/lookup-table failure drills, feed-forward on ambient temperature, replace placeholder parameters with site values
