# Whole-kiln simulation plan (stage 2)

**Status:** draft for team review, 2026-11-17. Nothing in this plan is implemented.
**Stage 1** is `project/simulation-upgrade-plan.md` (fan, orifice plate, chimney, visuals). Stage 2
starts after stage 1 is built and builds on it.
**Scope:** simulation on the dev machine only. No change to `fan-ctrl/`, `dashboard/` or hardware.

**Source of kiln knowledge:** the VelKilnMaster repository
(`https://github.com/smtwkla/VelKilnMaster`), read on 2026-11-16. File names below that start with
`docs/`, `sandbox/` or `backend/` refer to that repository unless they say otherwise.

---

## 1. Goal

Simulate the whole kiln, not only the exhaust end, so that the fan control can be tested against
realistic changes in the gas it receives before anything is tried on the real system.

Stage 1 treats the kiln as one box with a set gas temperature and a set resistance. Stage 2 replaces
that box with the real thing: a ring of fireboxes, a moving fire, dampers, fuel feeding and tiles.
The exhaust temperature, the gas flow and the resistance the fan sees then come out of the model
instead of being typed in.

---

## 2. What the kiln is

From `docs/Kiln-Domain.md`:

- A **Hoffman continuous kiln**: 60 fireboxes in a ring, in two batteries (East 1-30, West 31-60)
  joined by two interconnecting flues (north and south).
- Each firebox belongs to a **room unit** with a platform of tiles, a set of 4 portholes in the arch
  for fuel, and a K-type thermocouple ("point"). Two interconnecting-flue units have no platform.
- About 30 room units have a **damper** that connects the ring to a central **main flue**.
- The main flue leads to the **ID fan**, then the **orifice plate**, then the **chimney**.
- The fire travels clockwise. At the current schedule it moves about 9 room units per day, so one
  full round takes about a week.

Gas path at any moment:

```
open doors -> cooling zone -> firing zone -> pre-heating zone -> damper zone
 (ambient      (air heated     (fuel burns)   (gas heats and     (4-5 lifted dampers)
  air in)       by fired tiles)                dries green tiles)        |
                                                                         v
                                              main flue -> ID fan -> orifice plate -> chimney
```

A paper seal ahead of the damper zone stops air entering from the wrong side.

---

## 3. Model

### 3.1 Structure

| Part | Representation |
|---|---|
| Ring | 60 cells in firebox order, each a firebox plus (usually) a platform |
| Gas in the ring | One stream moving clockwise, solved cell by cell each step |
| Dampers | A branch from a ring cell to the main flue, with a lift in inches |
| Main flue | One node collecting all damper flows; its suction is what stage 1's fan and chimney produce |
| Fan, plate, chimney | The stage 1 model, unchanged |
| Brickwork | Arch, outer wall, inner wall and floor of each cell as layered solids that store heat |
| Tiles | Per platform: mass, temperature and remaining water |
| Operations | Doors, portholes ("top open"), paper seals, damper lifts, fuel charges, as timed events |

### 3.2 Physics

1. **Flow network.** Stage 1 gives the suction at the main flue for a given fan speed and gas
   temperature. That suction pulls gas through each lifted damper in parallel. Each damper is a
   cone lifting out of a 450 mm ring, so its open area grows with lift until the bore limits it.
   The ring upstream of each damper adds the resistance of the tile settings and fire flues.
   Flow through each damper, and through each ring cell, is solved from these resistances.
2. **Combustion.** A fuel charge adds heat and combustion products to its firebox cell. Fuel has a
   heating value, an air requirement, a moisture content and a burn-out time, so a charge releases
   its heat over minutes rather than instantly.
3. **Gas temperature.** Gas is treated as quasi-steady. In each cell it exchanges heat with the
   brick surfaces and the tiles and leaves at a new temperature. Energy is conserved by
   construction.
4. **Brick heating and cooling.** Each wall, arch and floor is a 1-D stack of layers with the
   rebuild materials, stepped in time.
5. **Tiles.** Tiles heat up, hold near 100 degC while water evaporates, then continue to the peak.
   Evaporated water joins the gas stream.
6. **Cooling zone.** Ambient air entering through open doors is heated by fired tiles and brick
   before it reaches the fire. Open portholes let some of it escape.
7. **Exhaust.** Flows from all lifted dampers mix in the main flue. The mixed temperature and
   total flow are what the fan, the plate and the chimney see.

Items 2 to 5 already exist for a chain of 9 fireboxes in `sandbox/coldstart_firing/model.py`
(about 1,400 lines, NumPy, 37 tests). Stage 2 extends that approach to the full ring.

### 3.3 Operations

| Operation | Rule in the model | Source |
|---|---|---|
| Fire travel | Constant rate, default 9 room units per day | Kiln Firing Schedule |
| Damper cycle | Raise 3.6 in/h to 9 in, hold, lower 2.0 in/h; 24 h in total; a new damper starts every second room unit | Kiln Firing Schedule |
| Combined lift | Sum of all open damper lifts stays about constant | Damper Operation Model |
| Fuel charge | Every 15 minutes, split over 4 portholes; 160 charges over 40 h per firebox | Firing Plan |
| Fuel recipe | Coal first at low weight, then firewood ramping up to a peak, then tapering; about 724 kg per firebox | Firing Plan |
| Conditional charge | Add fuel if the point reads below a threshold; skip if above | Firing Plan |
| Moisture adjustment | Charge weight increased for wetter firewood | Firing Plan |
| Cooling | Top open by operator judgement; door part-open 11 room units and full-open 14 room units behind the last firing firebox | Kiln Firing Schedule |
| Paper seal | Removed before the damper is lifted | Process flow |

Each rule is a parameter set, so a different schedule or firing plan can be tried.

### 3.4 Time

A round takes about a week, so the simulation must run much faster than real time. Brick and tile
states step every 1 to 5 simulated minutes; the gas network is solved at each step. The stage 1 fan
loop runs at its 1 s scan inside each step only when control behaviour is being studied; otherwise
the fan is assumed to hold its flow setpoint. Target: one simulated week in a few minutes on the
dev machine.

---

## 4. Known site values

| Item | Value | Source |
|---|---|---|
| Fireboxes | 60, with thermocouples polled every 60 s | `docs/Kiln-Domain.md`, `docs/Module-DAQ.md` |
| Room unit | 1880 mm long, 2743 mm wide, side wall 1220 mm, semicircular arch radius 1370 mm, inside volume 11.8 m3 | Room Unit Geometry |
| Tile load | 4000 tiles, 7600 kg wet, 7-10 % moisture, 500-690 kg water driven off | Tile load per room unit |
| Firing power | about 72 kW per firebox, about 15 firing at once | `docs/Kiln-Coldstart-Firing.md` |
| Firewood | 14.3 MJ/kg net at about 22 % moisture | same |
| Coal | 5400-5500 kcal/kg, 5-10 % ash; a higher grade at 7500-8000 kcal/kg | Fuel Types |
| Rates seen | Heating 12-21 degC/h, peak about 900 degC, cooling about 12 degC/h, up to 200 degC spread in one room | Profile Study |
| Damper | Cone in ring, 450 mm bore (approximate), maximum lift 23.5 in | Damper |
| Orifice plate | Between the ID fan and the chimney | Flue Flow Control System |
| P1, P2 | 0-250 Pa transmitters | same |
| Operating point | P1 119.2 Pa, P2 87 Pa, exhaust 130.4 degC, 380 rpm, 2.02 V output, displayed flow 40.33 | LabVIEW front-panel screenshot, 17-03-2026 |
| Legacy formula constants | C 0.7, A2 0.6096 m2, Z 0.98128836, M 89, k 1.4, R 8.3145, T in kelvin | Flue Flow Control System |
| ID fan | Resonance band 150-210 rpm, to be avoided | `docs/Kiln-Coldstart-Firing.md` |
| Chimney | 120 ft or 125 ft tall, about 3 ft square at the top | conflicting, see section 7 |
| Brick and insulation data | Density and conductivity for the rebuild materials | Material data |

Values assumed in the cold-start model, not measured: ID fan pressure 300 Pa at 380 rpm, the
resistance of the tile setting and flues (0.25 m2 equivalent), and baseline air leakage 150 kg/h.

---

## 5. Data needed for calibration

Without these the model shows the right behaviour but not the right numbers.

| Data | Where it is | Used for |
|---|---|---|
| Minute logs of P1, P2, exhaust temperature, flow, rpm | `C:\Labview-Logs\` on the SCADA PC | Fan and chimney calibration; golden tests for `calc_pv` in this repository |
| 60 firebox temperatures over several rounds | VelKilnMaster database (`temperature_readings`) | Checking the simulated temperature wave |
| Event history (damper lifts, fire start and stop, doors) | VelKilnMaster database (`kiln_events`) | Replaying real operation through the model |
| Firing plan workbook | `backend/data/Kiln Firing Schedule.xlsx` | Exact charge weights and conditions |
| Profile study | `backend/data/28 Feb 2026 profile study room 18.pdf` | Temperatures inside one room |
| ID fan curve or nameplate | site | Replacing the assumed fan pressure |
| Main flue and damper flue cross-sections | site | Replacing the assumed resistance |

---

## 6. Visuals

Stage 2 adds a kiln view next to the stage 1 fan-and-chimney scene:

- **Plan view of the ring:** 60 cells coloured by temperature, with the fire, the zones, open doors,
  lifted dampers and paper seals marked. The fire visibly moves round the kiln.
- **Section of one room unit:** brick layers, tiles and gas coloured by temperature, with remaining
  tile moisture.
- **Main flue:** flow from each lifted damper joining and leading into the stage 1 scene.
- **Charts:** temperature against position round the ring, temperature history of chosen points
  with the firing plan charges marked, fuel fed per hour, exhaust temperature and flow.
- **Controls:** schedule and firing plan parameters, fuel type and moisture, weather, time speed,
  and upsets such as a late charge, a damper left open or a door opened early.

---

## 7. Conflicts and open questions

1. **Drive model.** VelKilnMaster says ABB ACS 550; this repository's documents say ACS560-01-12A6-4.
2. **Present control hardware.** VelKilnMaster describes NI 9219 + LabVIEW + LabJack, with the PID
   inside the drive. This repository describes an Omron PLC running the PID. Which is on site now?
3. **Chimney height.** 120 ft in `docs/Kiln-Domain.md`; 125 ft in the cold-start document and from
   the owner on 2026-11-16. Stage 1 uses 125 ft.
4. **Legacy flow formula.** With the listed constants and the screenshot readings the formula gives
   about 1608 using the gauge pressure ratio and about 65 using absolute pressures. The screen shows
   40.33. A scaling or filtering step is missing. `backend/data/LabVIEW Flow Calc Formula.png` and
   the logs should settle it.
5. **Code reuse.** The cold-start model belongs to the VelKilnMaster repository. Copying or adapting
   it here needs that repository owner's agreement, and a decision on whether to copy it or depend
   on it.
6. **Fuel mix.** How much of the firing today is firewood, coal, sawdust or briquette?
7. **Operator behaviour.** Top-open timing and cooling-fan use are by judgement. The model needs a
   stated rule for each.
8. **Corners.** Special damper rules apply when the damper zone crosses an interconnecting flue;
   they are mentioned but not written down.

---

## 8. Order of work

Each step runs and is tested on the dev machine before the next starts.

| Step | Content | Result |
|---|---|---|
| 2.1 | Ring layout, zones and the moving schedule (fire position, damper lifts, door and top events) | The "train" moves round the ring; no physics yet |
| 2.2 | Flow network: dampers, ring resistance, main flue, joined to the stage 1 fan and chimney | Flow split between dampers; fan sees a changing resistance |
| 2.3 | Combustion and gas temperature along the ring, with fuel charges from the firing plan | Exhaust temperature and flow produced by the model |
| 2.4 | Brick and tile heating, drying and cooling | Temperature wave round the kiln |
| 2.5 | Kiln visuals and controls | Section 6 |
| 2.6 | Calibration against logs, then upset studies for the fan control | Report in `project/` |

Tests follow the stage 1 pattern: energy and mass balances close, flows through the dampers sum to
the main flue flow, a schedule with invalid timings is rejected, a firebox fed the standard plan
reaches a plant-like temperature, and the simulated wave moves at the scheduled rate.

Stage 2 is large. A realistic expectation is several working sessions, with step 2.6 dependent on
the data in section 5.
