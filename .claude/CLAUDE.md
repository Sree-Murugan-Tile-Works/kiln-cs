# CLAUDE.md

> **IMPORTANT:** Read `CLAUDE-COMMON.md` first — it contains general must-follow instructions (companion files, deployment model, workflow). This file contains repo-specific instructions. Anything here overrides `CLAUDE-COMMON.md`.
>
> **Also read `PROJ_STARTER.md`** — the owner's personal preferences (interaction rules, coding standards, tech stack choices, commit style). Both files were copied verbatim from the `kl-mithunvel/claude` template repo and reproduced below under `## User Rules`.

---

## Project Overview

`kiln-cs` (Kiln Control System) controls combustion-air fan speed on an industrial kiln and exposes a web dashboard for monitoring and configuration. It has two independent Python processes that communicate only through two shared SQLite databases:

- **`fan-ctrl/`** — a control daemon that reads pressure/temperature from a PLC, computes flow, runs PID or manual fan-speed control, and logs readings.
- **`dashboard/`** — a Flask app for viewing live readings/history and editing control parameters.

- **Author:** kl mithunvel
- **License:** none declared yet in this repo
- **Entry points:** `fan-ctrl/main.py`, `dashboard/web.py`
- **Runtime:** Python 3.10+ (uses `X | None` union type syntax)

---

## Running the System

Dev / simulation (no real PLC needed — see "Simulation vs real mode" below):

```bash
# Control daemon
cd fan-ctrl
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python config.py     # one-time: creates ../data/config.db with default parameters
python main.py

# Dashboard (separate shell)
cd dashboard
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export FLASK_APP=web.py
flask --app web run -h 0.0.0.0 -p 5001 --debug
```

Production dashboard:

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5001 web:app
```

Optional dashboard env vars: `APP_USER` / `APP_PASS` (HTTP Basic Auth on the `/config` and `/api/config` routes — disabled if unset), `FLASK_SECRET`, `CONFIG_DB`, `DATA_DB`.

No automated test suite exists yet (see Known Technical Debt).

---

## Architecture

| File | Role |
|------|------|
| `fan-ctrl/main.py` | Entry point; spawns the DAQ/PID thread, DB-writer thread, and queue-monitor thread; handles `SIGINT`/`SIGTERM` for clean shutdown |
| `fan-ctrl/plc.py` | `KilnPLC` — intended Omron FINS/TCP client (`fins` package) for the PLC link; reads P1/P2/T analog inputs, scales them, computes flow, writes motor RPM back |
| `fan-ctrl/calculation.py` | `Scaler` (raw↔engineering unit conversion), `MovingAverage` (rolling buffer), `calc_pv` (orifice-plate flow equation) |
| `fan-ctrl/pid.py` | `PIDController` — standard proportional/integral/derivative control |
| `fan-ctrl/fan_drive.py` | `FanDrive` — converts a PID % output or a manual RPM request into a clamped commanded RPM |
| `fan-ctrl/command.py` | Parses the `cur_cmd` config string (`"PID <setpoint>"` / `"MAN <rpm>"` / `"OFF"`) into a `Command` |
| `fan-ctrl/config.py` | Reads/writes the `config_params` table in `config.db`; produces an `AttrDict`-backed config object, reloaded every `RELOAD_CFG_IN` seconds |
| `fan-ctrl/dbwriter.py` | Background thread writing `kiln_data` rows to `data.db`; a second thread discards the oldest queued items if the queue backs up |
| `fan-ctrl/utils.py` | `AttrDict` — plain dict with attribute-style access |
| `dashboard/web.py` | Flask app: `/config` (view/edit params), `/dashboard` (latest reading), `/dashboard/graph` (matplotlib PNG, last hour), `/api/config` (JSON), `/config/export.json` |
| `dashboard/templates/` | Jinja2 templates (`web-config.html.j2`, `web-dashboard.html.j2`) |

### Data flow

```
PLC (FINS/TCP) --read_all()--> KilnPLC.data (FlowData: p1, p2, t, q, q_avg)
                                     |
                                     v
                  cur_cmd string -> Command (PID|MAN|OFF)
                                     |
                         PIDController.compute() / FanDrive.set_rpm()
                                     |
                                     v
                           FanDrive.commanded_rpm
                                     |
                                     v
                       KilnPLC.write() (motor RPM -> PLC)
                                     |
                                     v
                data_queue -> dbwriter.db_writer -> data.db (kiln_data table)

dashboard /config UI --writes--> config.db (config_params table)
                                     |
                                     v (reloaded every RELOAD_CFG_IN seconds)
                              fan-ctrl daemon

dashboard /dashboard, /dashboard/graph --reads--> data.db
```

### Threading model (`fan-ctrl/main.py`)

Three threads coordinated by a shared `threading.Event` (`stop_event`) and a bounded `queue.Queue` (`data_queue`, max 10000 items):

- `daq_pid` — reload config every `RELOAD_CFG_IN` seconds, read the PLC, run the control logic for the active command, push a result dict onto the queue, sleep until the next `cfg.scan_interval` tick.
- `dbwriter.db_writer` — drains the queue into `data.db`.
- `dbwriter.queue_monitor` — discards the oldest items once the queue exceeds 90% capacity (`QUEUE_MAX * 0.9`).

### Simulation vs real mode

There is no explicit sim/real toggle today. `KilnPLC.connect()`, `read_all()`, `write()`, `write_dm()`, and `read_dm()` are all stubbed with hardcoded raw values (see `fan-ctrl/plc.py`), so the rest of the control loop already runs end-to-end without a reachable PLC. Wiring up real `fins.tcp` reads/writes is the main blocker before this can run against hardware — see Known Technical Debt.

---

## Key Modules

- `plc.KilnPLC(cfg)` — `set_cfg(cfg)`, `connect()` (raises `ConnectionError` after `MAX_RETRIES` attempts with backoff), `read_all() -> bool`, `write()`, `write_watchdog()`, `close()`. Exposes `.data: FlowData` and `.com_ok: bool`.
- `pid.PIDController(cfg)` — `compute(process_variable, current_time) -> float`; stateful (`_integral`, `_previous_error`, `_last_time`); `reset()` clears state.
- `fan_drive.FanDrive(cfg)` — `set_output_percent(percent)`, `set_rpm(rpm)`, `off()`; always clamps to `[motor_min_rpm, motor_max_rpm]` via `clamp_motor_rpm`.
- `config.load_config_from_db(db_path) -> AttrDict`, `config.init_config_db(db_path)`, `config.get_param`/`set_param`, `config.conf_validate(cfg)`.
- `dbwriter.create_data_tables(db)` — creates the `kiln_data` table; `dbwriter.db_writer(queue, stop_event, db)` / `dbwriter.queue_monitor(queue, stop_event, high_level)`.
- `calculation.calc_pv(cfg, kiln_data)` — orifice-plate flow equation (see Key Conventions).

---

## Schema Reference

- `data/config.db` — table `config_params(name TEXT PK, type CHAR(1) ['i'|'f'|'s'], int_value, float_value, str_value, description, last_updated)`. Exactly one of the three value columns is non-NULL per row, enforced by a `CHECK` constraint (`fan-ctrl/config.py: create_config_db`). Read by the daemon every `RELOAD_CFG_IN` seconds; written by the dashboard `/config` UI.
- `data/data.db` — table `kiln_data(timestamp TEXT PK ISO-8601, q_value, q_avg, temp, pressure1, pressure2, pid_out, demanded_rpm, cmd_rpm, command, remarks)`. Write-mostly from `dbwriter.db_writer`; read by the dashboard.
- Both are SQLite in WAL mode. Neither schema file is git-tracked as DDL — the schema lives in `create_config_db`/`create_data_tables`.

---

## Key Conventions

- **Config value typing** — always go through `config.get_param` / `config.set_param` / `config.load_config_from_db` rather than reading the `int_value`/`float_value`/`str_value` columns directly; which column is populated depends on the row's `type`.
- **`cur_cmd`** — free-text command parsed by `command.Command`: `"PID <setpoint>"`, `"MAN <rpm>"`, or `"OFF"`. Invalid strings should fail closed to `OFF` (see `main.parse_cmd`).
- **Flow calculation (`calculation.calc_pv`)** — orifice-plate equation: `Q = C * A2 * sqrt(2*Z*R*T/M * K/(K-1) * ((P2/P1)^(2/K) - (P2/P1)^((K+1)/K)) * 1000)`. The constants (`c`, `a2`, `z`, `r`, `m`, `k`) come from `config_params`; `T` must be in the units those constants assume.
- **Two independent RPM ranges** — PID output is first mapped into `[pid_min_rpm, pid_max_rpm]` (`FanDrive.set_output_percent`), then clamped again to `[motor_min_rpm, motor_max_rpm]` (`clamp_motor_rpm`). Both ranges are configured separately and don't have to match.
- **`CONFIG_DB` / `DATA_DB` env vars** — override the default relative paths `../data/config.db` / `../data/data.db`, used by both `fan-ctrl/main.py` and `dashboard/web.py`. Both processes must point at the same files to see each other's data.

---

## Data Files

- `data/config.db`, `data/data.db` (plus their `-shm`/`-wal` siblings) — runtime SQLite databases, git-ignored (`data/.gitignore`), created on first run by `fan-ctrl/config.py` / `fan-ctrl/dbwriter.py`. Never commit these.
- No credentials are committed. `dashboard/web.py` reads `APP_USER` / `APP_PASS` / `FLASK_SECRET` from the environment only.

---

## Platform Constraints

- Pure Python; no OS-specific branching exists today.
- `fan-ctrl` depends on the `fins` package (Omron FINS protocol) for the eventual PLC link (`fan-ctrl/requirements.txt`).
- `dashboard` depends on Flask + matplotlib, using the `Agg` backend so it runs headless (`dashboard/requirements.txt`).
- No real hardware I/O happens yet — `plc.py` is fully stubbed. Once implemented it will need a TCP path to the PLC's FINS port (config default `9600`).
- Target field hardware: HMI Weintek cMT3072XH (local operator panel, independent of `dashboard/`), PLC Omron CP2E-N30DT1-D (FINS/TCP), fan drive ABB ACS560-01-12A6-4 (VFD), an orifice-plate flow element with two gauge-pressure transmitters (P1 upstream / P2 downstream, both vented to atmosphere) and one temperature sensor. Full detail, including open wiring/comms questions, in `project/hardware-overview.md`.

---

## Deployment Notes

Field hardware identities are now known (see `project/hardware-overview.md`): Omron CP2E-N30DT1-D PLC, Weintek cMT3072XH HMI, ABB ACS560-01-12A6-4 drive. Still undecided: the PLC↔drive command path (analog reference vs. Modbus), whether the PLC has the analog I/O modules needed for the pressure/temperature transmitters, and where the two Python processes (`fan-ctrl`, `dashboard`) will actually run. Fill in this section once those are settled — follow the Deployment Model in `CLAUDE-COMMON.md` (dev machine first, hardware last).

---

## Known Technical Debt

- 🔴 `fan-ctrl/plc.py` — `connect()` opens a `fins.tcp.TCPFinsConnection` but `read_all()`/`write()`/`read_dm()`/`write_dm()` never call into it; they return hardcoded raw values (`p1_raw = 4500`, `p2_raw = 4200`, `t_raw = 3360`). The PLC link is not actually wired up.
- 🔴 `fan-ctrl/plc.py: read_all` — has a standing `# todo: detect and handle negative values properly` for analog input readings.
- 🔴 `fan-ctrl/pid.py: PIDController.set_cfg` — assigns `self.kp = cfg.kp` three times; `ki` and `kd` are never read from config after construction (always `None`/default), so the integral and derivative terms can't be tuned at runtime.
- 🟡 `dashboard/web.py` — leftover `print()` debug statements in `coerce_for_type` and `config_save_one`.
- 🟡 No automated tests exist for `fan-ctrl` or `dashboard`.

---

## Development Rules

_Not yet formalized beyond the universal rules in `CLAUDE-COMMON.md` and the personal preferences in `PROJ_STARTER.md`. Add numbered project-specific rules here as they're agreed._

---

## Project TODO List

Tracked in `TODO.md` at the project root — keep that file current rather than duplicating it here.

---

## User Rules

> Standard User Rules copied verbatim from `CLAUDE-COMMON.md`, followed by personal preferences copied verbatim from `PROJ_STARTER.md`, per the process both files describe. Treat `CLAUDE-COMMON.md` itself as read-only — if it needs to change, that's a cross-project decision, not a per-project edit.

### Standard User Rules (from `CLAUDE-COMMON.md`)

#### Companion Files

Claude must maintain two files in every project root alongside `CLAUDE.md`. Create them on the first session if they do not exist.

##### `TODO.md` — Task Tracker

Tracks what has been done and what still needs doing. Update it whenever a task is started, completed, or discovered.

```markdown
# TODO

## In Progress
- [ ] <task>

## Done
- [x] <task> — <brief note on outcome>

## Not Started
- [ ] <task>
```

Rules:

- Move items from **Not Started → In Progress → Done** as work progresses. Never delete entries; they are the audit trail.
- Add newly discovered tasks immediately — do not hold them until the end of a session.
- Link to the relevant commit hash next to Done items where possible.

##### `Claude_log.md` — Session Log

Records what was actually done, session by session. Append a new entry at the start of every session and fill it in as work proceeds.

```markdown
# Claude Log

## YYYY-MM-DD — <one-line session summary>
- <action taken and outcome>
- <files changed and why>
- <decisions made and rationale>
- <anything left incomplete and why>
```

Rules:

- One dated entry per session. Multiple entries on the same date are allowed if there are distinct work blocks.
- Keep entries factual and concise — not a stream of consciousness. Focus on *what changed* and *why*.
- Both files must be committed alongside any code changes they describe. Never let them drift out of sync.

#### Deployment Model

**The hard rule: write and test on the development machine first. Hardware comes last.**

This applies to every project that has a hardware target (Raspberry Pi, Arduino, embedded Linux, remote server). It is not optional.

##### Stages — always in this order

1. **Code on dev machine** — write all logic, module interfaces, and data flows on the laptop/desktop. The dev machine is Windows or Linux; it has no GPIO, no I2C, no serial ports.
2. **Test on dev machine** — run the full test suite (`pytest`). Verify the feature works end-to-end using the simulation/dev stack (fake sensors, mock hardware, local SQLite). Fix all failures before moving on.
3. **Review for hardware impact** — before touching the device, explicitly state which parts of the change touch real hardware (GPIO pins, I2C addresses, serial ports, baud rates) and which parts are pure logic.
4. **Deploy to hardware** — only after steps 1–3 are complete. Transfer code via `git pull`, `rsync`, `scp`, or `arduino-cli` as appropriate for the project. Run the hardware smoke test.
5. **Verify on hardware** — run the hardware-specific test or verification script. Note any behaviour difference from simulation. If there is a discrepancy, fix it on the dev machine (step 1) and repeat — never patch directly on the device.

##### Rules that follow from this

- **Every hardware driver must have a simulated equivalent** that runs on the dev machine and produces the same data shape and exceptions. Code written without a simulation path cannot be tested in stage 2 and breaks the workflow.
- **Never hardcode hardware addresses, port names, or pin numbers in driver files.** They go in `config.yaml` and are passed as parameters. This lets the same code run in simulation (with dev values) and on hardware (with real values).
- **When proposing a change**, always separate it into: (a) logic that can be fully verified on the dev machine, and (b) hardware-specific parts that need device testing. State both explicitly so the user knows what to test where.
- **Never instruct the user to "just run it on the device"** as a substitute for a dev-machine test. If a test cannot be run on the dev machine due to a hardware dependency, say so clearly and explain what the device test will verify.

#### Commands & Workflow

- **Always activate the project virtualenv before running any Python command.** Use `source venv/bin/activate` (Linux/macOS) or `venv\Scripts\activate` (Windows). Never invoke `python` or `pip` bare without the venv active.
- Track all dependencies in `requirements.txt`. Pin at least the major version. Run `pip freeze > requirements.txt` after installing anything new.
- A migration to `uv` is planned. Flag `uv` as a recommended replacement whenever suggesting new tooling or packaging steps.
- Run lints (`python -m py_compile` at minimum, `flake8` or `ruff` if configured) and the test suite before every commit.

### Personal Preferences (from `PROJ_STARTER.md`)

#### Interaction Rules

- **Every git commit must include a co-author trailer** for `kl mithunvel <klm@smtw.in>`. Add the following line at the end of every commit message body (after a blank line):

  ```
  Co-authored-by: kl mithunvel <klm@smtw.in>
  ```

- **Always explain before acting.** Before making any code changes, edits, or file writes, describe exactly what you are going to do and wait for explicit confirmation from the user. List every file that will be changed and what will change in each. Do not proceed until the user says to go ahead.

#### Software Engineering Preferences

- **DRY (Don't Repeat Yourself):** Extract shared logic into reusable functions. Avoid copy-pasting code blocks.
- **Testing is important:** Write tests for new functionality. Cover the happy path and key failure modes. Use `pytest`; tests live in `tests/`.
- **Consider edge cases:** Think about nulls, empty inputs, boundary values, and concurrent access. Clarify with me if requirements are ambiguous.
- **Explicit over implicit and clever:** Write clear, readable code. Avoid magic numbers, obscure one-liners, and hidden side effects. If someone has to puzzle over what it does, rewrite it.
- **Proper error handling:** Handle errors at the right level. Return meaningful messages. Don't silently swallow exceptions.
- **Deprecation:** Never use deprecated APIs, functions, or modules. If found, rewrite to avoid them after consulting me.

#### General Principles

- **Simplicity first:** Minimal, straightforward code. No over-engineering.
- **Explain always:** Document your code and decisions. Explain choices and how things work.
- **Backend-heavy:** Prefer logic in the backend; keep frontends thin.

#### Tech Stack Preferences

| Layer | Choice | Notes |
|-------|--------|-------|
| Languages | Python (latest stable), JavaScript/TypeScript | |
| Backend frameworks | Flask, FastAPI | Flag when FastAPI would be a better fit than Flask |
| Frontend frameworks | Vanilla JS / lightweight frameworks | Keep it simple |
| Python GUI | Tkinter | When a desktop UI is needed |
| Database | SQLite (preferred for local/app data) | Never write to read-only external sources |
| Python packaging | pip + venv | Planned migration to `uv` — flag when recommended |
| Configuration | YAML | For all settings and config files |
| Infrastructure | Windows, Debian/Raspberry Pi OS, Ubuntu LTS | Guard any OS-specific code behind checks |

#### Commit Message Style

Use imperative mood, short subject line (≤ 72 chars), no trailing period:

```
Add CLAUDE.md for project X
Update TODO list after database integration
Fix Key Conventions section for encoding bug
Add Schema Reference for new data source
```

Do not use vague messages like `update`, `fix stuff`, or `changes`.

### Project-Specific Overrides

_None — add below as needed._
