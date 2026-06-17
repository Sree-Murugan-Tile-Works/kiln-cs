# TODO

## In Progress

## Done
- [x] Add Claude Code support files (`CLAUDE.md`, `CLAUDE-COMMON.md`, `PROJ_STARTER.md`, `.claude/skills/`) — bootstrapped from the `kl-mithunvel/claude` template repo
- [x] Document real field hardware (HMI/PLC/drive/sensors) and the orifice-plate formula mapping in `project/hardware-overview.md`; updated `CLAUDE.md` Platform Constraints/Deployment Notes accordingly

## Not Started
- [ ] Wire up real `fins.tcp` reads/writes in `fan-ctrl/plc.py` (currently stubbed with hardcoded raw values)
- [x] Fix `fan-ctrl/pid.py: PIDController.set_cfg` — `ki`/`kd` are never read from config (only `kp` is set, three times) — fixed, added `__main__` test block
- [ ] Handle negative analog-input values in `fan-ctrl/plc.py: read_all` (existing `# todo` in source)
- [x] Remove leftover debug `print()` calls in `dashboard/web.py` — removed in dashboard rewrite
- [x] Add a `pytest` test suite for `fan-ctrl` and `dashboard` — 60 tests across fan_ctrl (utils, calculation, pid, command, fan_drive, config, dbwriter) and dashboard (all API routes + coerce_for_type)
- [x] Create shared `requirements.txt` (project root, UTF-8) covering both fan-ctrl and dashboard packages; add `setup.bash` for one-command Pi bootstrap
- [ ] Wire `fan-ctrl/main.py` to call `dbwriter.log_error()` on PLC comm failures and other runtime errors
- [ ] Document a deployment target and fill in `CLAUDE.md`'s Deployment Notes section
- [ ] Decide and implement the PLC↔ACS560 drive command path (analog setpoint vs. Modbus) for `plc.py`/`fan_drive.py` (see `project/hardware-overview.md` §6)
- [ ] Confirm the CP2E-N30DT1-D has (or will get) the analog I/O module(s) needed for the 2 pressure transmitters + temperature sensor (see `project/hardware-overview.md` §4)
- [ ] Verify whether `calc_pv` should use absolute or gauge P1/P2 (sensors are gauge, vented to atmosphere) and whether `T` should be Celsius or Kelvin (see `project/hardware-overview.md` §7)
