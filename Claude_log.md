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

## 2026-11-14 (night, later) — Process simulation GUI
- Added `sim/server.py` (Flask; background runner thread steps the loop at 1x/5x/20x/60x/200x; endpoints /api/specs, /api/state, /api/params, /api/command, /api/fault, /api/control) and `sim/static/{index.html,style.css,app.js}` (sliders generated from the registry, mode/setpoint controls, fault injection, SVG schematic with fan and flow animation tied to the real rpm/flow, four canvas charts with hover readout, light/dark theme). Run: `python -m sim.server`, open http://127.0.0.1:5002.
- Checked it by running the server and rendering the page with headless Chrome (the Claude-in-Chrome extension was not connected, so no clicking; scenarios were driven through the API and the page screenshotted). Verified: sliders reflect and change the physics (cold front + taller chimney raised natural flow above the setpoint, fan pinned at its minimum; raising the setpoint made the fan take over), P2 open circuit gives the red "Sensor fault -> safe speed" state with the controller flow blank.
- Fixes found by looking at the screenshots: chimney labels overflowed; chart time axis showed negative times; start-up dipped the fan (the real `PIDController` is positional and has no bumpless transfer) -> `ClosedLoop._bumpless_start` pre-loads the integral on entering PID (simulation-side only), with 2 new tests.
- Tests: `tests/sim/test_server.py` (10 API tests). Full suite 266 passed.
- Not done: clicking through the GUI by hand (extension offline); YAML preset files for parameter sets; legacy `calc_pv` in the loop; PLC/drive twins and failure drills.

## 2026-11-14 (night, later still) — Correct the model: heat reuse is before the plate
- Owner correction: the hot-air heat reuse happens inside the kiln's own tunnels, BEFORE the orifice plate (not between plate and fan). Order is kiln (with reuse tunnels) -> duct -> plate -> fan -> chimney.
- `sim/plant.py`: `t_gas_c` is now the gas leaving the firing zone; `plate_temperature()` applies `reuse_extraction` to give the (lower) temperature at the plate, which is also the fan inlet and chimney base temperature; the reuse-tunnel loss now sits upstream of the plate and shows in P1/P2 (not in the plate dP). `OperatingPoint.t_fan_in_c` replaced by `t_kiln_c`. `sim/params.py` labels/groups updated; GUI schematic shows the tunnels inside the kiln box; charts show kiln gas and plate gas separately.
- Tests: 5 new tests in `tests/sim/test_plant.py`; full suite 271 passed.
- `project/process-description.md` open question 1 (plate position) is answered by this; left that file's edit to the owner's pending doc changes (see below).

## 2026-11-14 (late night) — Parameter-interaction report
- Owner asked for a report on how the parameters affect each other. New `sim/analysis.py` (probes, one-at-a-time sensitivity in two views, interaction grids, measurement-error and closed-loop studies) and `sim/report.py` (figures + Markdown); output `project/simulation-report.md` and `project/simulation-report/*.png`. Regenerate with `python -m sim.report`. `tests/sim/test_analysis.py` (14 tests). All numbers in the report come from the model, so it stays in step with it.
- Main findings (placeholder values, trends not magnitudes): duct diameter and plate beta dominate (1/D^4); gas molar mass is the largest uncontrollable factor; the fan adds 1.07-1.72 m3/s depending on the draft already present; flow the loop can hold has a floor set by natural draft at minimum fan speed; heat reuse acts through extraction (less draft) and tunnel loss (deeper suction at P1/P2 together) and the two compound; P2 reaches 108 % of the placeholder transmitter range at max rpm; controller estimate errors (Cd, molar mass, P1/P2 drift) become invisible true-flow errors (about 2-5 %); with this parallel-form PID Ki sets the speed and more Kp slows the final approach; without anti-windup recovery after 10 min of saturation took 1139 s versus 8 s.
- `project/process-description.md`: plate-position question answered (reuse before the plate), roadmap status updated. That file and the other project/*.md docs still carry the owner's earlier uncommitted edits; this commit does not include them.


## 2026-11-16 — Document review, manuals downloaded, connection diagram
- Owner asked for a review of all documents (PDFs first, then project docs) for pitfalls, then for missing manuals to be fetched from the internet and a connection diagram to be written.
- Read: all project docs, `TODO.md`, the 8-slide deck (rendered to images), TxRail manual, Weintek datasheet/installation sheet, HMI-PLC guide in full; W483, the CP1W pages and the Weintek JS chapter by targeted search.
- Downloaded 7 files into `project/reference-docs/` (about 137 MB): CP2E hardware W613 and software W614, FINS commands reference W342, CP1E-to-CP2E replacement guide, ACS560 firmware manual, ACS560 hardware manual (83 MB), cMT3072XH product sheet. Searched for specific facts only, not read cover to cover.
- New `project/connection-diagram.md`: block diagram, link list, AD041/TxRail/RS-485/drive terminal tables, Ethernet plan (Pi on CP2E PORT B, proposed 192.168.100.20), drive parameters the Modbus link depends on, 22 pitfalls, site verification checklist, draft Pi-to-PLC memory map. Every line tagged manual / deck / proposed / verify.
- Facts now confirmed from manuals: CP2E-N30 has a 2-port layer-2 switch and 3 user FINS/TCP connections (+1 for CX-Programmer); DM is in non-volatile RAM; no square-root instruction but `APR(069)` does 1-D float tables; AD041 open-circuit detection only on 1-5 V and 4-20 mA; drive is frame R1 with one combined S100 switch; ACS560 58.14 defaults to Fault and 58.15 to Cw/Ref1/Ref2.
- After the owner's go-ahead, applied the doc corrections: `project/hardware-overview.md` (§6 body rewritten as decided plus two open points; §10.3 pointer and Ethernet facts; §10.5 drive comms-loss row; §10.6 two 1-D `APR` tables proposed; §10.10; §11.1 design implications; §11.2-11.6; §12.2 corrected, 0-10 V has no open-circuit detection; §12.5 authority wording and HMI model note), `.claude/CLAUDE.md` (single root venv and `requirements.txt`, target data flow added above today's, Known Technical Debt refreshed, tests line), `project/implementation-plan.md` (`fins` call shapes confirmed).
- Left as they were: `hardware-overview.md` §4, §5 and §9 (older text, still accurate as history) and the rest of `implementation-plan.md`, which is to be regenerated after team approval.
- Full test suite: 285 passed. No source code changed. Nothing committed.

## 2026-11-16 — Simulation upgrade plan written for review
- Owner reviewed the simulation and asked for more visuals and calculations, with corrections:
  the orifice plate is between the fan and the chimney; heat reuse inside the kiln is not of
  interest; the chimney is 125 ft tall, 5 ft x 5 ft at the base and 3 ft x 3 ft at the top and
  must stay parametric.
- Read all of `sim/` and `tests/sim/`. Findings beyond the owner's points: the chimney is one
  lump with a single mean temperature, and outside air has one pressure and density at all heights.
- Owner decisions: particles represent air density / pressure; write the plan to `project/` first.
- Files added: `project/simulation-upgrade-plan.md` (layout, physics, new calculations, visuals,
  files to change, tests, open questions).
- Files changed: `TODO.md` (review task; process-description correction task).
- Noted in the plan: true-scale pressure differences are under 1 % of atmospheric and would not
  show in a particle count, so the plan proposes a labelled "Exaggerate pressure" switch.
- No code changes. Implementation waits for team review and an explicit go-ahead.

## 2026-11-17 — Whole-kiln simulation plan (stage 2) written for review
- Owner pointed to `https://github.com/smtwkla/VelKilnMaster` as the source of kiln knowledge.
  Cloned it to a scratch folder (not into this repo) and read `docs/Kiln-Domain.md`,
  `docs/Kiln-Coldstart-Firing.md`, `docs/Module-DAQ.md`, the cold-start model's structure and
  the LabVIEW flow-control screenshots. Not read: refractory PDFs, the firing schedule
  workbook, most of the application code.
- Found: the kiln is a 60-firebox Hoffman ring with about 30 dampers into a main flue; firing
  schedule, damper cycle and firing plan rules; a real operating point (P1 119.2 Pa, P2 87 Pa,
  130.4 degC, 380 rpm); legacy formula constants; an existing NumPy model of gas path, draught,
  fuel and brick heating for 9 fireboxes.
- Conflicts recorded, not resolved: ACS 550 vs ACS560; LabVIEW/NI 9219 vs Omron PLC as the
  present controller; chimney 120 ft vs 125 ft; the legacy formula with the listed constants
  gives about 1608 (gauge ratio) or about 65 (absolute), not the displayed 40.33.
- Owner decision: keep the committed plan as stage 1 and add a stage 2 for the whole kiln.
- Files added: `project/whole-kiln-simulation-plan.md`.
- Files changed: `project/simulation-upgrade-plan.md` (titled stage 1, pointer to stage 2, new
  §9 with site values found), `TODO.md` (three new tasks).
- No code changes.

## 2026-11-17 — Build plan for the staged simulation build
- Owner asked for a multi-stage build plan, with a commit after each stage.
- Added `project/simulation-build-plan.md`: stages A-J, design decisions for stages A and B, the
  operating-point mismatch (about 200 Pa lost between P2 and the chimney top), and a correction to
  the legacy formula figures (31.0 or 50.9 against 40.33 on screen, not 1608 or 65).
- Read all of `sim/`, `tests/sim/` and the legacy formula defaults in preparation.
- Not done: no stage is built. Work stopped at a usage limit before stage A started.

## 2026-11-17 — Build stage A: new exhaust-path physics
- `sim/plant.py` rewritten: kiln -> fan -> plate -> restriction -> chimney; heat reuse removed;
  tapered square chimney solved in 20 slices; outside air pressure falls with height; kiln gauge
  pressure now drives flow; full pressure walk and every loss reported.
- `sim/gas.py`: barometric pressure and air viscosity. `sim/params.py`: new parameter set, with
  kiln and restriction resistance written as equivalent free areas.
- Default case gives P1 121 Pa and P2 88 Pa at 380 rpm and 130.4 degC (site: 119.2 and 87).
- `sim/loop.py`, `sim/analysis.py` and tests adapted; chimney taper study added. 303 tests pass.
- Known gaps until later stages: `python -m sim.report` does not run (stage E); the GUI drawing
  still shows the plate before the fan (stage D); transmitters are still two-sided (stage B).

## 2026-11-17 — Build stage B: site realism
- Transmitters are one-sided (0 to `p_range_pa`, default 250 Pa) and saturate at 3.8 / 20.5 mA
  (-75 / 6188 counts). Suction cannot be read.
- Drive skips the resonance band (150-210 rpm); the record flags when the shaft is inside it.
- Legacy `calc_pv` is called unchanged with the fan-ctrl default constants and shown as
  `flow_legacy`. A characterisation test pins its value at the site reading (31.007).
- Kiln disturbances: fuel-charge pulses and a damper-cycle swing of the kiln free area (off by default).
- New analysis functions: legacy value against back-pressure, lowest readable fan speed, charge
  disturbance. 332 tests pass.
- Findings from the model (placeholder values, to be checked on site):
  - P2 goes below 0 Pa under about 245 rpm, so the flow cannot be measured there. With a low
    setpoint the loop under-reads the flow and the fan hunts.
  - The default minimum speed (220 rpm) is inside that unreadable region.
  - The legacy value is not a steady function of flow in this model: it peaks near 300 rpm and
    falls at higher speed, because P2/P1 rises with back-pressure. The real system was controlled
    with this value for years, so either the real back-pressure behaves differently from the
    modelled restriction, or the legacy inputs are not plain gauge pressures. A speed step test
    on site (rpm against P1 and P2) would settle it.

## 2026-11-17 — Build stage C: calculations and profile data
- New `sim/profile.py`: stations, chimney slices, outside air at matching heights, particle densities
  (true and exaggerated x100 for the picture only) and calculations (velocities, Reynolds numbers,
  pressure budget, fan air and shaft power, heat carried and lost, draft share).
- `/api/state` carries `profile` for the latest instant only; history records are unchanged.
- At the default point: 11.2 t/h of gas, 3.0 m/s in the duct, 4.2 m/s at the chimney exit, about
  1.1 kW of fan air power, 344 kW carried above ambient, 51 kW lost through the chimney wall.
- 352 tests pass.

## 2026-11-17 — Build stage D: the new picture
- New `sim/static/scene.js`: canvas scene with the tube coloured by gas temperature, particles for
  gas density (pressure / temperature) inside the tube and in a blue sky, a turning fan, the plate,
  the restriction and the tapered chimney drawn to height scale; labels at every station and for
  the outside air at ground and at the chimney top.
- "Exaggerate pressure" switch (on by default, x100, with a NOT TO SCALE note); pressure strip along
  the path; calculations panel with a pushing/resisting pressure bar; legacy value shown as a KPI
  and a chart; resonance band shaded on the speed chart; chimney sliders show feet.
- Checked with headless Edge screenshots at the default point, at 100 rpm and at 450 rpm. Not
  checked by eye: the true-scale view (switch off), the light theme, and a narrow phone-width window.
