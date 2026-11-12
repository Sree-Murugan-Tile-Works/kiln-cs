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
- No code changes. Open questions are listed in `project/process-description.md` §8.
- Noticed: CLAUDE.md Known Technical Debt still lists the `pid.py` set_cfg bug, the dashboard
  debug prints and "no tests exist", which `TODO.md` marks as done. Not changed here; flagged
  for a separate cleanup.
