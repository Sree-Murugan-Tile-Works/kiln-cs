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

## 2026-11-14 (later) — Read the Fan PID deck and remaining PDFs, update docs
- Copied `Kiln CS Fan PID.pdf` from Downloads to a new `docs/` folder as asked (the first request said the repo root; the later one said docs folder, so docs/ was used). The PDF is 8 slide images with hand sketches; read by rendering pages with PyMuPDF in a throwaway venv in the scratchpad (project venv and requirements untouched).
- Read: all 8 deck pages; full text of the TxRail, HMI datasheet/install and HMI-PLC guide; searched the CP1W unit pages, CP1E/CP2E instruction reference, CP2E hardware/software manuals and ACS560 quick-start guide. NOT read: ACS560 hardware manual (Drive reader returned empty), ACS560 firmware manual beyond about the first 236k characters (Modbus chapter not reached), SigNow installer and TxRail zip contents.
- Findings added to `project/hardware-overview.md`: §12 (deck: temperature transmitter wiring, AD041 detail, PLC pulse/PWM outputs and terminal layout, architecture sketch with HMI-to-ACS560 RS-485 link, network table with IPs, ACS560 default I/O, PIDAT instruction features, design consequences, new questions); §11.1/11.3 corrections (open-circuit code 8000 confirmed at below 3.2 mA, counts are two's complement in -300..6300, 0-10 V output wiring shown, other CP1W units); §11.6 read-coverage table.
- `.claude/CLAUDE.md`: negative-values debt line now explains the two's complement and 8000 facts. `TODO.md`: new Done entry and three Not Started items.
- Decisions: sketch readings are marked as interpretation; nothing committed. Left open: how the PLC sends the speed reference, PIDAT constants, drive parameters, ACS560 Modbus register map.

## 2026-11-14 (evening) — Agree the Pi-supervisor architecture; update docs; publish approval page
- Design discussion with the owner (14 numbered questions). Outcome: the Omron PLC, Weintek HMI and ABB ACS560 STAY; a Raspberry Pi 5 CM is ADDED as supervisor. This reverses the 2026-11-13 direction that the PLC, HMI and VFD would be replaced.
- Key points: the PLC cannot do a square root (checked: no root instruction in the CP1E/CP2E instruction reference; float +,-,*,/ exist), so the Pi runs calc_pv and writes flow plus a heartbeat to the PLC; the PLC runs the PID; if the heartbeat goes stale the PLC uses a 2-D flow table over (P2/P1, T) generated from calc_pv; the HMI bridges the demanded RPM to the drive over RS-485 Modbus (single master); run/stop and E-stop are hardwired and the Pi never stops the fan; sensor fault or table failure gives a fixed safe RPM; drive comms loss gives a safe speed by the drive's own setting. Earlier answers superseded by this: Pi-side ADC, Pi commanding the drive, replacing the HMI.
- Files changed: `project/hardware-overview.md` (status banner, headings of sections 2/4/5/6, section 10 rewritten as the agreed architecture with roles, connections, fail-safe table, table design, decisions log, phases, software consequences, open questions; section 11.5 and 11.7 and section 12 notes aligned), `.claude/CLAUDE.md` (plc.py row, Process Context, Platform Constraints, Deployment Notes, negative-values debt note), `project/process-description.md` (scope, roadmap, open questions), `project/implementation-plan.md` (update banner listing superseded and still-valid parts; phases not rewritten), `TODO.md` (tasks reworded, new tasks, FINS wiring task reinstated).
- Published the shareable approval page (artifact, private until the owner shares it): https://claude.ai/artifact/QTxBwFJL4baTap6qoHf4Ba
- Not done: no code changed; implementation-plan.md phases still need regenerating after team approval; safe RPM, timeouts, PLC-failure behaviour, Pi-to-PLC memory map and ACS560 comms-loss parameters are open. Nothing committed yet.

## 2026-11-14 (night) — Process simulation: physics core
- Owner asked for a fully parametric simulation (natural draft through a hot chimney, orifice plate, fan control) with sliders, using general placeholder values; order of work: physics core + tests + commit, then GUI, run and check it, then commit.
- New package `sim/`: `params.py` (single registry of 45 parameters with default/range/unit/help, drives validation and the GUI sliders), `gas.py`, `plant.py` (closed-form flow solve from the pressure balance draft + fan curve = resistances, damped iteration for chimney cooling; dynamic plant with drive ramp, motor lag, gas inertia, thermal lag), `instruments.py` (transmitters to PLC counts 0-6000 with lag, noise, offset, open-circuit 8000 and stuck faults; controller flow estimate with wrong-Cd / wrong-gas assumptions), `loop.py` (closed loop on the real `PIDController`, `FanDrive`, `Command`, `Scaler`; safe speed on sensor fault and on OFF; conditional-integration anti-windup).
- Tests: `tests/sim/` (131 tests); full suite 254 passed. `pytest.ini` now also puts the repo root on the path so `import sim` works.
- Decisions: flow estimate in the loop is a clean orifice equation, NOT `calc_pv` (its units are unverified and its constants must not be touched); P1/P2 are gauge and go negative under suction; incompressible gas for the pressure balance; a stopped fan is a passive restriction; anti-windup lives in the sim wrapper because `PIDController` has none. All parameter values are placeholders, not site data.
- Left: GUI (next), legacy `calc_pv` in the loop, PLC/drive twins and failure drills.

