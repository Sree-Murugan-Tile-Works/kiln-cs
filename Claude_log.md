# Claude Log

## 2026-11-13 — Process context documented
- Owner described the process: wood-fired kiln exhaust (flue gas) ducted to heat-reuse
  stages; natural draft plus chimney suction; fan used when draft is insufficient; orifice
  plate measures flow; an ambient temperature sensor is also available.
- Clarified sensors: P1/P2 are differential transmitters with the low side open to room, so
  they read gauge pressure ("gauge-via-DP"), not true absolute.
- Owner stated `calc_pv` is an empirically tweaked equation (about 20+ years old) and not in
  exact engineering units. Decision: preserve behaviour, add characterisation tests before any
  change, never normalise constants without an explicit owner decision.
- Scope: plate, instruments, kiln and chimney stay the same; the control system is changing
  first. A visual GUI simulation is planned later (to be planned in `project/` first).
- Files added: `project/process-description.md`, `Claude_log.md`.
- Files changed: `.claude/CLAUDE.md` (Process Context pointer, `calc_pv` convention note,
  tech-debt entry), `TODO.md` (new tasks).
- Owner then clarified the scope: the PLC and software are being replaced by a Raspberry Pi,
  a new HMI and a new VFD. Omron CP2E, Weintek HMI, ACS560 and the FINS link are now legacy.
- Docs updated for that: `project/hardware-overview.md` (legacy banner, legacy tags on §2 and
  §4–6, new §10 with the new system, design choices, architecture direction and safety
  requirements), `project/process-description.md` (§5, roadmap, open questions),
  `.claude/CLAUDE.md` (Process Context, Platform Constraints, Deployment Notes, `plc.py`
  row), `TODO.md` (new control-system tasks; FINS-wiring task marked superseded).
- Decisions: Pi is the single control authority; every real driver gets a simulated twin;
  addresses/ports go in YAML; safety/fail-safe design is required before commissioning.
- Left open: sensor interface, VFD model and command path, HMI model, cutover plan, power-cut
  behaviour (all listed in `hardware-overview.md` §10).
- No code changes. Open questions are listed in `project/process-description.md` §8.
- Noticed: CLAUDE.md Known Technical Debt still lists the `pid.py` set_cfg bug, the dashboard
  debug prints and "no tests exist", which `TODO.md` marks as done. Not changed here; flagged
  for a separate cleanup.
