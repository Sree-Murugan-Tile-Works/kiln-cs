# Claude Log

## 2026-06-16 — Bootstrap Claude Code support for kiln-cs
- Added `CLAUDE.md` documenting the actual fan-ctrl daemon and dashboard architecture, data flow, SQLite schema, key conventions, and known technical debt (stubbed PLC I/O in `plc.py`, `pid.py` never setting `ki`/`kd`, debug `print()`s in `dashboard/web.py`).
- Copied `CLAUDE-COMMON.md` and `PROJ_STARTER.md` verbatim from the `kl-mithunvel/claude` template repo; their content is also reproduced inside `CLAUDE.md`'s `## User Rules` section per the documented process.
- Added `.claude/skills/pdf/SKILL.md`, `.claude/skills/grill-me/SKILL.md`, and `.claude/skills/update-docs/SKILL.md`, copied from the template repo's `.CLAUDE/skill/` (moved to the lowercase `.claude/skills/` path so Claude Code actually discovers them in this project).
- Created this log file and `TODO.md` as the companion files `CLAUDE-COMMON.md` requires, seeded with the technical debt items already visible in the codebase.
- Nothing left incomplete from this task. Future sessions should keep `TODO.md` and this log updated per `CLAUDE-COMMON.md`'s rules.

## 2026-06-16 — Document real field hardware and orifice-plate formula
- User described the actual field hardware: Weintek cMT3072XH HMI, Omron CP2E-N30DT1-D PLC, ABB ACS560-01-12A6-4 fan drive, an orifice-plate flow element with two gauge-pressure transmitters (P1 upstream / P2 downstream, both vented to atmosphere), and one temperature sensor, used to control draft airflow out of a Hoffman-type kiln.
- Created `project/hardware-overview.md`: hardware inventory, sensor wiring topology, PLC↔software and PLC↔drive link status, a variable-by-variable walkthrough of `calculation.calc_pv`'s orifice-plate equation tied to the physical sensors and `config_params`, and an open-questions list (PLC↔drive comms method, analog I/O module availability, gauge-vs-absolute pressure and Celsius-vs-Kelvin temperature assumptions in the flow formula, the unusually high default molecular weight `m=89`).
- Updated `CLAUDE.md`: Platform Constraints now names the real target hardware; Deployment Notes now reflects that the hardware BOM is known but the PLC↔drive comms method and process deployment host are still undecided.
- Updated `TODO.md`: marked hardware documentation as Done; added Not Started items for the PLC↔drive comms decision, confirming PLC analog I/O capacity, and verifying the pressure/temperature unit assumptions in `calc_pv`.
- Nothing left incomplete from this task; the open questions above are tracked in `TODO.md` for follow-up once the user has answers.

## 2026-06-17 — Build comprehensive live dashboard + fix pid.py ki/kd bug

### Changes
- **`fan-ctrl/pid.py`** — Fixed long-standing bug: `set_cfg` was assigning `self.kp` three times and never setting `self.ki` / `self.kd`, making integral and derivative terms always `None` (would crash on first non-zero time delta). Added `__main__` sanity-check block (same pattern as `calculation.py`) — confirmed output is sensible.
- **`fan-ctrl/dbwriter.py`** — Added `create_error_log_table(db)` (creates `error_log` table in `data.db`) and `log_error(db, code, source, message)` helper; updated `create_data_tables` to also call `create_error_log_table` and added `IF NOT EXISTS` to the `kiln_data` DDL. Cleaned up internal string formatting.
- **`dashboard/web.py`** — Major extension (backwards-compatible): removed `print()` debug statements; added 10 new API routes (`/api/live`, `/api/history`, `/api/pid` GET/POST, `/api/pid/presets` GET/POST, `/api/pid/presets/<id>/apply` POST, `/api/pid/presets/<id>` DELETE, `/api/errors`, `/api/command`); added `_ensure_extra_tables()` (creates `pid_presets` in `config.db` and `error_log` in `data.db` on startup); changed `/dashboard` to render new template.
- **`dashboard/templates/kiln_dashboard.html`** — New full-page live dashboard: 6 SVG gauges (P1/P2 full circular dials, Exhaust Temp thermometer, Flow Q/PID Output/Motor RPM semicircular arc gauges) all rendered via a JavaScript `GaugeBase` class with correct polar-coordinate math; PID control panel (view + inline edit form + named presets with save/load/delete); Command panel (PID/MAN/OFF mode toggle with appropriate inputs); two Chart.js waveform charts (RPM+Q dual-axis, Exhaust Temp); error log table. Live data polled at 2 s from `/api/live`; history preloaded from `/api/history`; errors polled at 10 s.

### Decisions
- All gauge geometry (arc paths, needle rotation) uses a single angle convention: 0° = 12-o'clock, clockwise positive. Circular dials: startDeg=225°, sweep=270°. Semicircular gauges: startDeg=270°, sweep=180° (arc drawn clockwise through top). Verified with polarXY math before writing.
- `pid_presets` table lives in `config.db` (alongside `config_params`); `error_log` lives in `data.db`. Both created lazily by the Flask app on startup — fan-ctrl daemon does not need updating to use the dashboard.
- fan-ctrl daemon will pick up PID parameter changes on its next `RELOAD_CFG_IN` cycle (unchanged behaviour).
- Chart.js loaded from CDN; graceful fallback message shown if unavailable.

### Left incomplete
- `main.py` not yet wired to call `log_error()` — fan-ctrl still logs errors only to Python's `logging` module, so the error log table will be empty until that is done (tracked in TODO.md).

## 2026-06-18 — Add setup.bash and fix requirements.txt encoding

- **`requirements.txt`** — Re-saved as UTF-8 (was UTF-16 LE from PowerShell `pip freeze`). Content unchanged: all 20 packages pinned. UTF-16 causes `pip install` to fail silently on Linux/Pi.
- **`setup.bash`** — New project-root bootstrap script for Pi. Steps: Python ≥ 3.10 check, `data/` creation, single shared `.venv` at project root, `pip install -r requirements.txt`, `fan-ctrl/config.py` (creates config.db with defaults), `dbwriter.create_data_tables` (creates data.db). Ends with a per-step ✓/✗ report and run instructions.

## 2026-06-17 — Fix three frontend/backend integration gaps in kiln_dashboard.html

### Changes
- **`dashboard/templates/kiln_dashboard.html`** — Three JS fixes:
  1. **Stale detection**: `livePoll()` now computes actual age of last timestamp (`Date.now() - new Date(ts)`) and shows 'stale' only if older than 15 s; previously it showed 'online' for any row that had a timestamp, even if hours old.
  2. **Command badge**: `applyLive()` now reads `d.cur_cmd` (the string written to config.db by the dashboard) rather than `d.command` (the last executed command logged by the daemon, which can lag up to RELOAD_CFG_IN seconds behind what was requested).
  3. **Immediate badge update on Apply**: the `btn-apply-cmd` click handler now updates `#cur-cmd-badge` to `d.cmd` immediately after a successful POST to `/api/command`, so the UI reflects the new command without waiting for the next 2 s poll.

### No incomplete items from this block
