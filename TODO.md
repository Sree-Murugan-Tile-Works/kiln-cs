# TODO

## In Progress


## Done
- [x] Add Claude Code support files (`CLAUDE.md`, `CLAUDE-COMMON.md`, `PROJ_STARTER.md`, `.claude/skills/`) — bootstrapped from the `kl-mithunvel/claude` template repo

## Not Started
- [ ] Wire up real `fins.tcp` reads/writes in `fan-ctrl/plc.py` (currently stubbed with hardcoded raw values)
- [ ] Fix `fan-ctrl/pid.py: PIDController.set_cfg` — `ki`/`kd` are never read from config (only `kp` is set, three times)
- [ ] Handle negative analog-input values in `fan-ctrl/plc.py: read_all` (existing `# todo` in source)
- [ ] Remove leftover debug `print()` calls in `dashboard/web.py`
- [ ] Add a `pytest` test suite for `fan-ctrl` and `dashboard`
- [ ] Document a deployment target and fill in `CLAUDE.md`'s Deployment Notes section
