# Kiln Fan Control — CM5 Software Design (dashboard, logging, PID, PLC comms)

> **Status: under team review.** No source files (Phases A–H below) have been touched yet.
> Implementation starts only after explicit go-ahead — see "Execution Mode" at the bottom.

## Context

The owner is moving from "code that runs end-to-end against stubs" to a real deployment:
a Raspberry Pi Compute Module 5 (CM5), running 24/7, attached to a monitor, talking to the
Omron CP2E-N30DT1-D PLC, which in turn relays the fan speed reference to the ABB ACS560
drive. Three architectural forks were just resolved by the owner:

1. **PLC protocol: FINS** (keep the existing `fins`/`fins.tcp.TCPFinsConnection` code path —
   no protocol rewrite).
2. **Drive control: the PLC relays the RPM to the ACS560** — the Pi only ever talks to the
   PLC, never to the drive directly.
3. **GUI: kiosk browser on the existing Flask `dashboard/`** — no new GUI framework.

This plan implements what's needed to make that real: wiring up the actual FINS reads/writes
in `plc.py` (currently fully stubbed), fixing bugs that would otherwise break PID control the
moment it's exercised for real, adding a manual-control/PID-tuning surface to the dashboard
for the kiosk screen, and producing the 24/7-on-Pi deployment artifacts (systemd units, kiosk
autostart notes). Per `CLAUDE-COMMON.md`'s Deployment Model, the PLC wiring is built so the
existing stub behavior remains available as an explicit **simulate mode** — so everything
below stays testable on the dev machine without the real PLC, and only the real DM register
addresses are deferred until they're known.

Two real bugs were found while tracing the PID path for this design (not yet in `TODO.md`):

- `fan-ctrl/main.py` (`daq_pid`, PID branch): calls
  `pid_ctrl.compute(plc.FlowData.q_avg, read_time)` — `plc.FlowData` is the **dataclass
  class**, not the `kiln_plc.data` **instance**; `FlowData` has no defaulted fields, so this
  attribute doesn't exist on the class at all. This raises `AttributeError` the instant `cur_cmd`
  is `PID ...`. Must be `kiln_plc.data.q_avg`.
- `fan-ctrl/pid.py` (`PIDController.set_cfg`): assigns `self.kp = cfg.kp` three times; `ki`/
  `kd` are never read from config, so the integral/derivative terms are always `None` and
  `compute()` would raise `TypeError` on `self.ki * self._integral` once gains are nonzero
  defaults (already tracked in `TODO.md`).

## Phase A — Bug fixes (do first, low risk)

- `fan-ctrl/main.py`: fix `plc.FlowData.q_avg` → `kiln_plc.data.q_avg` in the PID branch of
  `daq_pid`.
- `fan-ctrl/pid.py`: fix `set_cfg` to set `self.kp = cfg.kp`, `self.ki = cfg.ki`,
  `self.kd = cfg.kd`.
- `dashboard/web.py`: remove the leftover debug `print()` in `coerce_for_type` and the
  `print(sql, params)` in `config_save_one`.

## Phase B — Config additions (new `config_params` rows + one env var)

In `fan-ctrl/config.py: parameters_definition`, add DM register addresses as config-driven
values (consistent with how every other PLC-facing constant already lives here, e.g.
`p1_plc_min`), defaulting to `0` as an explicit placeholder until the real PLC program's
memory map is known:

- `dm_addr_p1`, `dm_addr_p2`, `dm_addr_t` — analog input DM addresses for P1/P2/T.
- `dm_addr_motor_rpm` — DM address the PLC reads to get the commanded RPM to relay to the
  ACS560.

Add one new env var (alongside the existing `RELOAD_CFG_IN`/`CONFIG_DB`/`DATA_DB` pattern in
`fan-ctrl/main.py`, since this is an infra-level "which backend" switch, not a live-tunable
control parameter): `PLC_SIM` (default `"1"`, i.e. simulate by default — safe default for the
dev machine; set to `"0"` on the CM5 once real wiring is verified).

## Phase C — Real FINS I/O in `fan-ctrl/plc.py`, gated by `PLC_SIM`

Refactor so `read_dm`/`write_dm` become the actual low-level primitives, and `read_all`/
`write` call into them per-channel (reuses the existing `Scaler` pattern — also wire up the
already-defined-but-unused `rpm_plc_min/max`/`rpm_eng_min/max` config pair into a `Scaler` for
the RPM output, same as `scl_p1`/`scl_p2`/`scl_t`):

- `connect()`: if `PLC_SIM`, no-op + `com_ok = True` (today's effective behavior). Else, keep
  the existing real `fins.tcp.TCPFinsConnection` logic as-is.
- `read_dm(addr, count)` / `write_dm(addr, data)`: if `PLC_SIM`, return/accept the current
  hardcoded stub values (`p1_raw=4500`, `p2_raw=4200`, `t_raw=3360`) so dev-machine behavior is
  unchanged. Else, perform the real FINS memory-area read/write via `self.fins_con`.
  **Verify the exact `fins` package method name/signature at implementation time** (e.g.
  `memory_area_read`/`memory_area_write`) by installing `fins==1.0.5` in a venv and inspecting
  it — it isn't installed anywhere in this repo today, so I haven't confirmed the call shape
  yet and won't guess at it in this plan.
- `read_all()`: calls `read_dm` for each of `cfg.dm_addr_p1/p2/t`, keeps the existing
  `plc_ai_error` fault-detection logic and scaling/averaging logic unchanged.
- `write()`: scales `self.data.motor_rpm` through the new RPM `Scaler` and calls
  `write_dm(cfg.dm_addr_motor_rpm, raw_rpm)`.
- Leave the negative-raw-value handling as a clearly marked follow-up (existing `# todo` in
  source) — the real analog input module's sign convention isn't known yet; not blocking this
  phase since simulate mode doesn't need it and real values aren't available to test against
  yet.

## Phase D — `fan-ctrl/main.py` wiring

- Call `kiln_plc.connect()` once before the `daq_pid` loop starts (today it's never called at
  all — `read_all()` is called directly).
- On `com_ok == False`, attempt a reconnect (`kiln_plc.connect()`, which already has its own
  retry/backoff) before the next scan, instead of logging the same error forever. In `PLC_SIM`
  this path is simply never hit.

## Phase E — Dashboard: Control Panel for the kiosk screen

No new backend routes — reuse the existing `/config/save/<name>` (`config_save_one`) endpoint,
which already round-trips through `coerce_for_type` and is already behind the optional
`APP_USER`/`APP_PASS` gate.

- Extract the per-row "name/value/save button" form markup currently inline in
  `dashboard/templates/web-config.html.j2` into a shared partial,
  `dashboard/templates/_param_row_form.html.j2`, included from both templates (DRY — avoids
  duplicating the type-aware `<input>` logic).
- `dashboard/web.py: dashboard()`: also query `config_params` (via the existing `get_db`
  helper) for `WHERE name IN ('cur_cmd','kp','ki','kd','set_point')` and pass those rows to the
  template as `control_rows`.
- `web-dashboard.html.j2`: add a "Control Panel" card above/near "Current Readings" that
  renders `control_rows` through `_param_row_form.html.j2` — gives the kiosk monitor one page
  with live readings, mode/setpoint/manual-RPM control, and PID gain tuning, without needing
  the generic `/config` table.

## Phase F — Tests (`tests/`, pytest, per `PROJ_STARTER.md`)

New `tests/` directory at repo root with a `conftest.py` adding `fan-ctrl/` and `dashboard/` to
`sys.path` (neither is a package today — flat scripts with sibling imports):

- `test_pid.py` — regression test that `set_cfg` actually sets `kp`/`ki`/`kd` (locks in the
  Phase A fix), plus basic `compute()` behavior (pure proportional step, integral accumulation,
  derivative sign).
- `test_calculation.py` — `Scaler` round-trip (`to_engineering`/`to_raw`), `MovingAverage`
  window/resize behavior, `calc_pv` sanity case (`p1 == p2` → ratio terms cancel).
- `test_command.py` — `Command` parses `PID <f>`/`MAN <i>`/`OFF`, raises `ValueError` on
  garbage input.
- `test_config.py` — `init_config_db`/`set_param`/`get_param` round-trip against a
  `tmp_path` sqlite file, including the new `dm_addr_*` params.
- `test_plc_sim.py` — with `PLC_SIM=1`, `KilnPLC.connect()`/`read_all()`/`write()` behave like
  today's stub (documents and locks in the dev-machine-testable path).

Real FINS wire-protocol behavior against actual hardware is explicitly **not** covered by
these tests — that's a hardware-stage verification step (Deployment Model stage 5), not
something fakeable on the dev machine without misrepresenting confidence.

## Phase G — Deployment artifacts for the CM5 (new `deploy/` folder)

- `deploy/fan-ctrl.service` — systemd unit: `python main.py` from `fan-ctrl/` inside its venv,
  `Restart=on-failure`, `Environment=PLC_SIM=0`, `CONFIG_DB`/`DATA_DB` set consistently.
- `deploy/dashboard.service` — systemd unit: `gunicorn -w 2 -b 0.0.0.0:5001 web:app` from
  `dashboard/` (matches the production command already documented in `CLAUDE.md`),
  `Restart=on-failure`, same `CONFIG_DB`/`DATA_DB`.
- `deploy/README.md` — install steps (`systemctl daemon-reload`, `enable --now` both units) and
  kiosk-browser autostart notes (Chromium `--kiosk http://localhost:5001/dashboard`) — marked
  **(verify on the actual CM5 OS image)** since the exact autostart mechanism depends on which
  desktop environment Raspberry Pi OS is running, which can only be confirmed on the device
  itself (Deployment Model stage 4/5, not guessable from the dev machine).

## Phase H — Docs

- `project/hardware-overview.md`: mark protocol/drive-control/GUI questions resolved (§6/§9);
  leave real DM addresses and AI sign-convention as the remaining open items.
- `.claude/CLAUDE.md`: Key Modules/Architecture gain the new config params, `PLC_SIM`, and the
  dashboard Control Panel; Deployment Notes describes the CM5 + systemd + kiosk-browser setup.
- `TODO.md`: move resolved items to Done; keep the DM-address and AI-sign-convention items as
  Not Started.
- `.claude/Claude_log.md`: new dated entry summarizing this session's design + changes.

## Execution Mode

Two separate approvals, not one:

1. **Done:** this document saved to `project/implementation-plan.md` for the owner to read and
   share with their team.
2. **Later, on explicit go-ahead (e.g. after team review):** implement Phases A–H in one
   continuous autonomous pass — no per-file confirmation stops, per the owner's instruction
   that this overrides the repo's normal "explain and wait for go-ahead" rule for this
   specific, already-reviewed plan. Progress will be reported as it happens.

## Verification

- `python -m py_compile` on every changed `.py` file (per `CLAUDE-COMMON.md`'s pre-commit rule).
- `pytest tests/` — all new tests green, with `PLC_SIM` defaulting to simulate so no real PLC
  is needed.
- Manually run both processes as today (`python main.py`, `flask --app web run ...`), confirm
  `/dashboard` now shows the Control Panel, editing `cur_cmd`/`kp`/`ki`/`kd`/`set_point` from it
  round-trips through `config_save_one` exactly like `/config` does, and that switching
  `cur_cmd` to `PID ...` no longer crashes (Phase A fix).
- Real-FINS and real-drive behavior (Phase C's non-`PLC_SIM` path, Phase G's systemd/kiosk
  setup) can only be confirmed on the CM5 against the real PLC — call this out explicitly as
  the remaining hardware-stage step once the DM register map is known.
