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

## 2026-11-14 — Add vendor-document data for sensors and control unit
- Read the owner's Google Drive vendor folder (14 files). Fully read: TxRail-USB manual, HMI
  datasheet, HMI-PLC connection guide. Partly read: CP1W analog unit pages (AD041/DA041 specs)
  and the first ~130 pages of the ACS560 firmware manual. Not read: the other PDFs.
- Anonymous curl downloads from Drive returned HTML sign-in pages (folder is not public); those
  were deleted. Used the authenticated Drive download tool instead: 8 files copied to
  `project/reference-docs/`; 6 files over its 10 MB limit could not be fetched.
- `project/hardware-overview.md`: temperature row and controller row updated; new §11 added
  (TxRail-USB specs and sensor-failure currents, CP1W-AD041/DA041 specs confirming the
  0–6000 count scaling, ACS560 Modbus/STO/PID facts, HMI datasheet facts, CM5 carrier-board
  considerations, file index, new open questions).
- `TODO.md`: new Done entry and Not Started items. No code changed.
- Decisions: CM5 notes in §11.5 are general knowledge, flagged to verify. Nothing committed.
- Left open: ACS560 Modbus register map (manual chapter not reached), P1/P2 transmitter model,
  carrier board, whether to commit the PDFs.
