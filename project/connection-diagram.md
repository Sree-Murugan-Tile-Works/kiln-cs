# Connection Diagram and Wiring Reference

Written 2026-11-16 from a review of every document in `project/reference-docs/`, the owner's
deck `docs/Kiln CS Fan PID.pdf`, and the project docs. It covers the architecture agreed on
2026-11-14 (`hardware-overview.md` §10): the PLC, HMI and drive stay, a Raspberry Pi 5 Compute
Module is added as a supervisor.

**Nothing in this file has been checked on site.** Every line carries one of these tags:

| Tag | Meaning |
|---|---|
| **[M]** | Stated in a manufacturer manual in `project/reference-docs/` (source named) |
| **[D]** | Drawn or printed in the owner's deck |
| **[P]** | Proposed here, not yet agreed |
| **[V]** | Unknown or inferred. Must be verified on site or in the PLC/HMI project before use |

Do not wire or commission from this document until the [V] items in §9 are closed.

---

## 1. System block diagram

```
                                   PLANT LAN 192.168.16.x  [D]
                                            |
                                            | LAN 1  192.168.16.19 [D]
   +----------------------+         +-------+----------------+
   | Raspberry Pi 5 CM    |         | Weintek cMT3072XH      |
   | (new, supervisor)    |         | HMI (stays)            |
   | calc_pv, heartbeat,  |         | operator panel and     |
   | logging, Flask UI    |         | PLC-to-drive bridge    |
   +---+--------------+---+         +---+----------------+---+
       | Ethernet     | HDMI            | LAN 2          | CON A (COM2 RS-485 2W)
       | 192.168.100.20 [P]             | 192.168.100.1  | pin 1 D-, pin 2 D+, pin 5 GND [D][M]
       |              v                 | [D]            |
       |        kiosk monitor           |                | RS-485 Modbus RTU
       |                                |                | (HMI = the only master)
       | FINS/TCP port 9600             | FINS/TCP 9600  |
       |                                |                |
   +---+--------------------------------+---+            |
   | PORT B [P]                  PORT A [D] |            |
   |   Omron CP2E-N30DT1-D (stays)          |            |
   |   192.168.100.7 [D]                    |            |
   |   2 ports = built-in layer-2 switch [M]|            |
   |   runs the PID (PIDAT) [V]             |            |
   |   +--------------------------------+   |            |
   |   | CP1W-AD041 analog input unit   |   |            |
   |   | IN1  IN2  IN3  IN4             |   |            |
   +---+--+----+----+----+--------------+---+            |
          |    |    |    |      | CIO 100.00 pulse? [D][V]|
          |    |    |    |      | (today's speed signal)  |
         P1   P2    T   ambient T                         |
        [V channel order]       v                         v
                          +-----+-------------------------+-----+
   hardwired Run/Stop --->| DI1 (13)                 X5 29 B+   |
   switch [V]             | DI5 (17) or AI1 (2) [V]     30 A-   |
                          |                             31 DGND |
   hardwired E-stop  ---->| X4 Safe Torque Off                  |
   (2 channels) [V]       |   ABB ACS560-01-12A6-4, frame R1 [M]|
                          +------------------+------------------+
                                             | U V W
                                          fan motor --> fan --> chimney
```

Process order (owner, 2026-11-14): kiln with heat-reuse tunnels, duct, orifice plate
(P1 upstream, P2 downstream, T), fan, chimney.

---

## 2. Who talks to whom

| # | Link | From | To | Medium / protocol | Carries | Status |
|---|---|---|---|---|---|---|
| L1 | Sensor loops | P1, P2, T, ambient T | CP1W-AD041 | 4-20 mA or 0-10 V, shielded twisted pair | Analog signals | exists; signal type per channel **[V]** |
| L2 | HMI to PLC | cMT3072XH LAN 2 | CP2E PORT A | Ethernet, FINS/TCP, port 9600, PLC station 0 | Screens, setpoints, tags | exists **[D][M]** |
| L3 | Pi to PLC | Pi Ethernet | CP2E PORT B | Ethernet, FINS/TCP, port 9600 | Pi reads counts, demanded RPM, status. Pi writes flow and heartbeat | new **[P]** |
| L4 | HMI to drive | cMT CON A (COM2) | ACS560 X5 | RS-485 2-wire, Modbus RTU | Today "status" **[D]**. Planned: speed reference too (decision 12) | exists; planned use **[P]** |
| L5 | PLC to drive | CP2E output (pulse) | ACS560 DI5 or AI1 | Hardwired | Today's speed reference, drawn as a pulse train on slide 5 | **[V]** see §8 item 14 |
| L6 | Run / stop | Operator switch | ACS560 DI1 | Hardwired contact | Start/stop | **[V]** |
| L7 | Emergency stop | E-stop button | ACS560 X4 (STO) | Hardwired, 2 channels | Removes torque | **[V]** |
| L8 | Pi display | Pi HDMI | Monitor | HDMI | Kiosk browser on the Flask dashboard | new **[P]** |
| L9 | Plant LAN | cMT LAN 1 | Plant switch | Ethernet | Remote HMI access | exists **[D]** |

Rules that the wiring must preserve (`hardware-overview.md` §10.5):

- The drive has exactly one Modbus master (the HMI). The Pi has no RS-485 connection.
- The Pi has no wire to the drive and no wire to any sensor.
- Run/stop and E-stop reach the drive without passing through any computer.

---

## 3. Sensors to the analog input unit (L1)

### 3.1 CP1W-AD041 terminals **[M]** (W471 pages, deck slide 2)

```
 upper row:   I IN1  V IN2  COM2   I IN3  V IN4  COM4   AG
 lower row:  V IN1  COM1   I IN2  V IN3  COM3   I IN4   NC
```

| Input type | Wiring |
|---|---|
| Voltage (0-10 V, 1-5 V, 0-5 V, ±10 V) | signal + to `V INx`, signal - to `COMx`. Input impedance 1 MΩ min |
| Current (4-20 mA, 0-20 mA) | **link `V INx` to `I INx`**, signal + to that pair, signal - to `COMx`. About 250 Ω |

- Shielded 2-core twisted pair; shield to FG at the unit end.
- No isolation between the four channels. Photocoupler isolation to the PLC only.
- Unused inputs: short `V IN` to `COM` (manual wiring note).

### 3.2 Channel plan **[V]**

The channel order is not in any document. The order below is an assumption to be replaced
with the real one from the PLC program.

| Channel | Signal | Transmitter | Signal type | Range code (word n+1 / n+2) |
|---|---|---|---|---|
| IN1 | P1, upstream gauge pressure | model unknown **[V]** | 4-20 mA assumed **[V]** | `10` (4-20 mA) **[V]** |
| IN2 | P2, downstream gauge pressure | model unknown **[V]** | 4-20 mA assumed **[V]** | `10` **[V]** |
| IN3 | T, gas temperature at the plate | Novus TxRail-USB | 0-10 V per deck slide 1, or 4-20 mA **[V]** | `01` (0-10 V) or `10` **[V]** |
| IN4 | Ambient temperature | unknown **[V]** | **[V]** | **[V]** |

With the ambient sensor the unit is full. A fifth signal needs a second expansion unit
(up to three in total on an N30 **[M]** W613).

### 3.3 PLC words **[M]**, position **[V]**

If the AD041 is the first expansion unit on the N30 CPU:

| Word | Content |
|---|---|
| CIO 2, 3, 4, 5 | Converted counts for IN1...IN4 (0000...1770 hex = 0...6000; convertible -300...6300) |
| CIO 102 | Set data for inputs 1 and 2 (bit 15 = 1, then use / averaging / range code per input) |
| CIO 103 | Set data for inputs 3 and 4 |

The CPU's own I/O uses CIO 0-1 (inputs) and CIO 100-101 (outputs); expansion units follow from
CIO 2 and CIO 102 in connection order (W614). If another unit sits before the AD041 the words
shift.

### 3.4 Pressure transmitter loops **[V]**

Typical 2-wire loop, to be confirmed against the real transmitters:

```
 +24 V DC ----> [+ P1 transmitter -] ----> V IN1 + I IN1 (linked)
                                            COM1 ----> 0 V of the same 24 V supply
```

Each transmitter's low-pressure port is open to the room, so the reading is gauge pressure
(`process-description.md` §2).

### 3.5 Temperature transmitter, Novus TxRail-USB **[M]** manual, **[D]** slide 1

```
 RTD (Pt100 or Pt1000, 3-wire):   terminals 1, 3, 4   (2-wire: link 3 and 4 per the spec text)

 0-10 V output (as drawn on slide 1):
     supply +  ----> 5 (+)        supply 12...30 V DC
     supply -  ----> 6 (-)
     7 (+) ----> AD041 V IN3
     8 (-) ----> AD041 COM3       (6 and 8 are joined inside the transmitter)

 4-20 mA output (alternative, 2-wire loop on the supply terminals, manual Fig. 18):
     +24 V ----> 5 (+)      6 (-) ----> AD041 V IN3 + I IN3 (linked)      COM3 ----> 0 V
     supply 10...30 V DC; max loop load = (Vdc - 10) / 0.02 Ω  (700 Ω at 24 V)
```

- No isolation between sensor input, output and the USB port. Do not connect the USB
  configuration cable while the RTD is in the process.
- RTD lead resistance must be equal in all three wires, 25 Ω max per wire.
- Which output is really in use, the programmed range and the failure direction are **[V]**.

---

## 4. Ethernet (L2, L3, L9)

| Device | Port | Address | Source |
|---|---|---|---|
| Weintek HMI | LAN 1 | 192.168.16.19 (plant LAN) | **[D]** slide 6 |
| Weintek HMI | LAN 2 | 192.168.100.1 | **[D]** |
| Omron CP2E | PORT A | 192.168.100.7 | **[D]** |
| Omron CP2E | PORT B | same IP as PORT A (the two ports are one layer-2 switch) | **[M]** W613 |
| Raspberry Pi | Ethernet | 192.168.100.20 / 255.255.255.0, static | **[P]** |

- The CP2E-N30 has two Ethernet ports with a built-in switching hub (W613; N14/N20 do not).
  The Pi can plug straight into PORT B. No extra switch is needed. Confirm PORT B is free **[V]**.
- FINS/TCP connections on the CP2E-N: **3 for the user plus 1 reserved for CX-Programmer**
  (W614 §15-2-2). The HMI uses one and the Pi one, leaving one spare.
- The PLC's FINS node address is set in the PLC Setup, not on a switch (W614). The Omron default
  ties it to the last octet of the IP, which would make it 7, but read the real value from
  the PLC Setup **[V]**. The Pi's own node address is handed out automatically during the
  FINS/TCP handshake, so no fixed client node is needed.
- On this network the Pi has no route to the plant LAN and no internet: no NTP, so the carrier
  board's RTC matters, and the dashboard is reachable only from the kiosk monitor. If plant-LAN
  access to the dashboard is wanted, the Pi needs a second network interface. Decision **[V]**.
- The HMI connection guide notes that the Weintek driver switches the PLC from RUN to MONITOR
  mode on initialisation.

---

## 5. HMI to drive, RS-485 Modbus RTU (L4)

### 5.1 Wires **[D]** slide 6, pins confirmed in **[M]** Weintek datasheet and ACS560 manuals

| Weintek CON A (9-pin D-sub female), COM2 RS-485 2W | Wire | ACS560 X5 |
|---|---|---|
| Pin 1, Data- | twisted pair, core 1 | 30, A- |
| Pin 2, Data+ | twisted pair, core 2 | 29, B+ |
| Pin 5, GND | third core | 31, DGND |
| shell | cable shield, grounded at one end | SCR / grounding clamp |

- COM3 RS-485 is on pins 6 (Data-) and 9 (Data+) of the same connector. The deck uses COM2.
- The drive is frame **R1** (12A6-4, 12.6 A, 5.5 kW; hardware manual ratings table). On frames
  R0-R2 there is **one** switch, `S100 TERM & BIAS`, default off. With only two devices on the
  line the drive is the last unit, so S100 should be ON. Whether the Weintek end needs an
  external 120 Ω resistor is **[V]**.
- The datasheet in the repo is for the **cMT3072XH2**; the deck says **cMT3072XH**. The XH
  product sheet from Wachendorff is now also in `reference-docs/`. Check the nameplate and the
  pinout of the fitted unit **[V]**.

### 5.2 Drive parameters that this link depends on **[M]** ACS560 firmware manual, values **[V]**

| Parameter | Meaning | Default | Needed |
|---|---|---|---|
| 58.01 Protocol enable | Turns on the embedded fieldbus | None | Modbus RTU |
| 58.03 Node address | Modbus slave address | 1 | must match the HMI |
| 58.04 / 58.05 | Baud rate / parity | 19.2 kbps / - | must match the HMI |
| 58.14 Communication loss action | What the drive does when Modbus stops | **Fault (drive trips)** | **Speed ref safe** |
| 58.15 Communication loss mode | Which messages reset the timer | Cw / Ref1 / Ref2 | see note |
| 58.16 Communication loss time | Timeout | 3.0 s | to be set with the process owner |
| 28.41 Frequency ref safe (22.41 Speed ref safe in vector mode) | The safe speed | 0 | the agreed safe speed |
| 58.06 Communication control | Refresh settings | - | needed after changing group 58 |
| 20.01, 28.11 / 22.11 | Start/stop source, reference source | DI1, AI1 (ABB standard macro) | start/stop stays on DI1; reference from EFB ref1 |

Default holding registers, ABB Drives profile: 400001 control word, 400002 reference 1,
400003 reference 2, 400004 status word, 400005 actual 1, 400006 actual 2. Each can be
remapped with 58.101...58.106.

Notes:

- With the default `58.14 = Fault`, a rebooting HMI or a pulled connector **trips the drive and
  stops the fan**. That contradicts the agreed "go to a safe speed" behaviour, so 58.14 and
  28.41 must be set before the HMI carries the reference.
- With the default `58.15 = Cw / Ref1 / Ref2`, only **writes** of the control word or a
  reference reset the timer. An HMI that only reads status does not. The HMI must rewrite the
  reference periodically, faster than 58.16, even when the value has not changed.
- Loss monitoring is active only when control or reference is expected from the fieldbus.
- The installed drive's parameters are unknown. Take a parameter backup first **[V]**.

---

## 6. Drive control terminals (L5, L6, L7)

ABB standard macro defaults **[M]** (deck slide 7, hardware manual). The parameters actually
set on the installed drive are **[V]**.

| Terminal | Name | Default function | Used for |
|---|---|---|---|
| 1 | SCR | Signal cable shield | shields |
| 2, 3 | AI1, AGND | Frequency reference 0-10 V | candidate for today's PLC speed signal **[V]** |
| 4 | +10V | Reference voltage, 20 mA max | - |
| 5, 6 | AI2, AGND | Not configured | - |
| 7, 8, 9 | AO1, AO2, AGND | Output frequency, output current | - |
| 10, 11 | +24V, DGND | Auxiliary 24 V, 250 mA max | supply for DI contacts |
| 12 | DCOM | Digital input common (jumpered to DGND at the factory) | - |
| 13 | DI1 | Stop (0) / Start (1) | **hardwired Run/Stop switch** |
| 14 | DI2 | Forward / reverse | - |
| 15, 16 | DI3, DI4 | Constant frequency selection | option: hardwired fixed safe speed |
| 17 | DI5 | Ramp selection. **Can be a frequency input, 0-16 kHz** | candidate for today's PLC pulse signal **[V]** |
| 18 | DI6 | Not configured | - |
| 19-21 | RO1 | Ready run | - |
| 22-24 | RO2 | Running | option: to a PLC input |
| 25-27 | RO3 | Fault (-1) | option: to a PLC input |
| 29, 30, 31 | B+, A-, DGND | Modbus RTU | HMI (§5) |
| X4 | STO | Safe Torque Off, factory jumpers fitted | **E-stop** |

### 6.1 Run / stop **[V]**

```
 X2: 10 (+24 V) ----[ Run/Stop switch ]---- X2: 13 (DI1)        12 (DCOM) jumpered to 11 (DGND)
```

### 6.2 Emergency stop into Safe Torque Off **[V]**

Both STO inputs must be closed for the drive to run. The drive ships with **jumpers** from
`OUT1` to `IN1` and `IN2`. An E-stop only works if those jumpers were removed and a
two-channel E-stop contact was wired in their place:

```
 OUT1 ----[ E-stop contact 1 ]---- IN1
 OUT1 ----[ E-stop contact 2 ]---- IN2
```

The terminal numbers disagree between documents: the default-connection table on deck slide 7
gives, for frames R0-R2, `34 SGND, 35 OUT1, 36 IN1, 37 IN2`; the hardware manual's technical
data lists `34 OUT1, 35 OUT2, 36 SGND, 37 IN1, 38 IN2`. **Read the labels on the drive itself
and do not rely on the numbers.** STO removes torque and the fan coasts down; it is not a
controlled stop.

### 6.3 Today's PLC speed signal (L5) **[V]**

Slide 5 draws a pulse train from the PLC to the drive, and slide 3 lists the CP2E pulse outputs
(CIO 100.00, 100.01, 101.00, 101.01; 1 Hz-100 kHz; PWM 2-6553.5 Hz). The CP2E base unit has no
analog output. Two wirings would fit:

| Candidate | PLC side | Drive side | Check |
|---|---|---|---|
| Pulse frequency | CIO 100.00 pulse output (DT1 = sourcing, 24 V) | DI5 as frequency input, group 11 parameters, 16 kHz max | drive 11.xx parameters; wire on terminal 17 |
| PWM to analog | PWM output through a converter or filter | AI1, 0-10 V | a converter module in the cabinet |

A sourcing (PNP) PLC output driving a drive digital input needs the PLC output supply's 0 V
joined to the drive's DGND/DCOM.

---

## 7. Power and the Pi

| Device | Supply | Source |
|---|---|---|
| CP2E-N30DT1-D | 24 V DC (`-D` model) | **[M]** |
| CP1W-AD041 | from the CPU bus: 5 V DC 100 mA, 24 V DC 90 mA | **[M]** |
| Weintek cMT3072XH2 | 24 V DC ±20 %, 820 mA, start-up peak up to 2 A | **[M]** |
| TxRail-USB | 10-30 V DC (4-20 mA) or 12-30 V DC (0-10 V) | **[M]** |
| Pressure transmitters | **[V]** | - |
| ACS560 control | internal; its +24 V output is 250 mA max. External 24 V input exists on frames R6-R8 only, so not on this R1 drive | **[M]** |
| Raspberry Pi 5 CM | carrier board with a 24 V DC input | **[P]** |

- Weintek: do not power the HMI from the same supply as inductive DC loads or controller input
  circuits (installation guide).
- Omron: with voltage inputs sharing one supply, an open wire puts roughly 1/3 to 1/2 of
  another channel's voltage on the broken input. Use separate supplies or isolators.
- The Pi's carrier board needs Ethernet, 24 V input, RTC with battery, hardware watchdog, DIN
  rail mounting, eMMC or NVMe and a display output (`hardware-overview.md` §11.5). No ADC and
  no RS-485.

---

## 8. Pitfalls found in the review

**Sensor fault detection**

1. A failed temperature transmitter is **not** caught by the `8000` check. TxRail's factory
   failure mode is upscale, above 20.5 mA, which the AD041 converts to about 6190 counts (it
   converts up to 6300). Downscale, below 3.8 mA, gives about -75 counts. `8000` appears only
   below 3.2 mA. The PLC needs band checks on counts as well as the `8000` test.
2. Open-circuit detection exists **only on the 1-5 V and 4-20 mA ranges** (W471). On 0-10 V a
   broken wire reads near 0 V, or a ghost value when supplies are shared. `hardware-overview.md`
   §12.2 says otherwise and is wrong. If T is on 0-10 V, moving it to 4-20 mA gives real
   wire-break detection.
3. The AD041 reports `0000` for two scans plus about 50 ms after power-up, and converts nothing
   until the range codes are written (first-cycle flag A200.11).
4. Negative counts are normal: -300...-1 arrive as FED4...FFFF hex and must be sign-converted.

**Flow calculation**

5. `calc_pv` raises on ordinary inputs: P1 = 0 (division by zero), P2/P1 above 1 or negative
   (square root of a negative number). `KilnPLC.read_all` does not catch it.
6. The plate is on the fan's suction side, where both gauge pressures would be negative and
   P2 the more negative, giving a ratio above 1. The `__main__` example uses positive values
   (143.24 and 103). The real sign convention must be known before the fallback table is built.
7. `calculation.py`'s `__main__` example and `config.py`'s defaults disagree (`a2` 0.6096
   against 0.6096², different `z` and `r`, and T = 408 against a 0-250 range). Decide which is
   the legacy system before writing golden tests.

**Fallback table**

8. A 2-D table is not needed. `T` is a plain multiplier inside the square root, so
   `Q = g(T) × h(P2/P1)`: two 1-D tables and one floating-point multiply. The CP2E has
   `APR(069)` for 1-D line-segment tables with floating-point data (W483); it holds the end
   value outside the table instead of extrapolating. W483 has no square-root instruction, so
   the reason for the Pi stands.
9. The Pi's flow is a 60-sample average and the table's is not, and `PIDAT` does no bumpless
   transfer, so switching between the two sources will step the PID input.
10. DM, Holding and Counter areas are kept in non-volatile RAM without a battery (W614), so a
    table in DM survives a power cut. Only the clock needs the battery.

**Pi-to-PLC link**

11. The `fins` library (1.0.5, installed) negotiates node addresses itself, so the
    `dest_node_address = 1` and `src_node_address = 25` config defaults are unused. Node 1 is
    also what the HMI's IP would map to.
12. The same library exposes `change_to_program_mode`, `change_to_run_mode` and program-area
    writes. The Pi code must call only `memory_area_read` and `memory_area_write`.
13. After `connect()` the library's socket has no timeout, so a silent link blocks the scan
    thread forever. Set a socket timeout.
14. The heartbeat must be incremented in the same pass that read the counts, calculated the
    flow and wrote it successfully. A heartbeat from a separate thread would keep a stale
    flow looking healthy.
15. A 32-bit float occupies two words with the low word at the lower address; the library has
    `reverse_word_order` for this.
16. The log-only phase needs no PLC program change: the Pi can read CIO 2-5 directly.

**Drive path**

17. Slide 5 shows the PLC already sending speed to the drive directly. Decision 12 moves the
    reference onto the HMI, which puts HMI reboots and project downloads inside the control
    loop. Alternatives that keep the HMI out: keep the existing signal, or fit a serial option
    board (CP1W-CIF11/12 or CP2W-CIFD) and use the PLC's Modbus-RTU Easy Master. Worth a
    decision before Phase 4.
18. Drive defaults work against the fail-safe plan (§5.2): comms loss trips the drive, and a
    read-only master does not keep the link alive.
19. The standard macro is scalar control with a **frequency** reference in Hz. The project
    talks in RPM (`motor_max_rpm` = 450). The RPM-to-Hz conversion, and whether 450 is fan or
    motor speed, is not written down anywhere.
20. The E-stop may not act on the drive at all if the STO jumpers are still fitted (§6.2).

**Hardware identity**

21. HMI model: deck says cMT3072XH, repo datasheet is cMT3072XH2 (§5.1).
22. The TxRail has no input-to-output isolation and the AD041 none between channels. A
    grounded RTD sheath can create a ground loop through the analog commons.

---

## 9. Site verification checklist

Sensors and analog unit
- [ ] P1 and P2 transmitter make, model, range, output signal and supply.
- [ ] Which AD041 channel carries which signal; link fitted between V IN and I IN on current inputs.
- [ ] Range codes written to CIO 102 / 103 in the PLC program; averaging on or off.
- [ ] Position of the AD041 in the expansion chain (confirms CIO 2-5).
- [ ] TxRail: output type in use (0-10 V or 4-20 mA), programmed range, failure direction, probe type.
- [ ] Sign of P1 and P2 in normal running (positive or suction), with typical values.
- [ ] Ambient temperature sensor: type, location, channel.

PLC
- [ ] CX-Programmer project (`.cxp`): DM map, PIDAT words, scaling, how `min_RPM` is chosen.
- [ ] PLC Setup: FINS node address, FINS/TCP connection settings, IP of the built-in port.
- [ ] PORT B free; cable route to the Pi.
- [ ] Which output carries the speed signal today and what it is wired to (§6.3).
- [ ] Serial option boards fitted, if any.

HMI
- [ ] Nameplate: cMT3072XH or XH2; OS and EasyBuilder Pro version.
- [ ] Weintek project (`.cmtp`): Modbus settings for COM2, what is read and written on the drive.
- [ ] Termination at the HMI end of the RS-485 cable.

Drive
- [ ] Parameter backup (macro, groups 11, 20, 22, 28, 46, 58).
- [ ] S100 position.
- [ ] STO terminals: jumpers or E-stop contacts; terminal labels as printed on the drive.
- [ ] What is on DI1, DI5 and AI1.
- [ ] Motor nameplate (poles, rated speed) and any belt or gear ratio to the fan.

Pi
- [ ] Network choice: PLC link only, or a second interface on the plant LAN.
- [ ] Carrier board chosen; 24 V supply capacity for the added load.

---

## 10. Draft Pi-to-PLC memory map **[P]**

Addresses are placeholders until the PLC project shows which DM words are free. The layout is
what matters: one contiguous block written by the Pi, one read by the Pi, so each scan is one
FINS write and one or two FINS reads.

Written by the Pi (one block):

| Offset | Type | Content |
|---|---|---|
| +0 | UINT | Heartbeat counter, +1 after each successful read, calculate, write pass |
| +1, +2 | REAL | Flow `q` from `calc_pv` (low word first) |
| +3, +4 | REAL | Averaged flow `q_avg` |
| +5 | WORD | Pi status bits: flow valid, calculation error, config reloaded |

Read by the Pi:

| Source | Type | Content |
|---|---|---|
| CIO 2...5 | INT ×4 | Raw counts P1, P2, T, ambient (signed; 8000 = open circuit) |
| block B +0 | UINT | Demanded RPM (PID or manual output after the selector) |
| block B +1 | WORD | PLC status: flow source in use (Pi / table), mode (PID / MAN / min), sensor alarm bits |
| block B +2, +3 | REAL | Flow value the PID is actually using |
| block B +4 | WORD | Drive status word, copied in by the HMI |
| block B +5 | UINT | Setpoint in PLC units |

PLC-side rules to give the PLC programmer: declare the Pi dead when the heartbeat has not
changed for the agreed timeout; return to the Pi only after several consecutive changes;
range-check the flow before using it; hold the fallback tables in DM.

---

## 11. Reference documents

In `project/reference-docs/`. Files marked *new* were downloaded on 2026-11-16.

| File | Content | Source |
|---|---|---|
| `w613_cp2e_hardware_users_manual_en.pdf` *new* | CP2E hardware manual W613-E1-03 (326 p) | files.omron.eu |
| `w614_cp2e_software_users_manual_en.pdf` *new* | CP2E software manual W614-E1-03 (578 p): Ethernet, FINS, PLC Setup, memory | files.omron.eu |
| `w342_fins_commands_reference.pdf` *new* | Omron communications commands reference W342-E1-15 (FINS command set) | farnell.com copy |
| `p150_cp1e_to_cp2e_replacement_guide_en.pdf` *new* | CP1E to CP2E replacement guide P150-E1-02 | files.omron.eu |
| `ACS560_firmware_manual_IGPKA216x_en.pdf` *new* | ACS560 standard control program firmware manual (526 p): parameters, embedded fieldbus | library.e.abb.com |
| `ACS560_hardware_manual_3AXD50000044998_en.pdf` *new* | ACS560 hardware manual (216 p, 83 MB): terminals, STO, ratings | search.abb.com |
| `cMT3072XH_datasheet_wachendorff.pdf` *new* | Product sheet for the older cMT3072XH (distributor edition) | wachendorff-prozesstechnik.de |
| `w483_cp1e_cp2e_cpu_unit_instructions_reference_manual_en.pdf` | CP1E/CP2E instruction reference | owner's Drive |
| `CP1W-AD_DA_MAD_TS_DRT_SRT Pages from W471-E1-04.pdf` | CP1W analog unit pages | owner's Drive |
| `cMT3072XH2_Datasheet_ENG_20240619.pdf`, `GMEC72X2N_cMT3072X2_XH2_Installation_20240619.pdf` | Weintek XH2 datasheet and installation sheet | owner's Drive |
| `HMI PLC Connection Guide OMRON_CJ_CS_CP_Ethernet_FINS_TCP.pdf` | Weintek to Omron FINS/TCP setup | owner's Drive |
| `Chapter-43-JS-Object-and-JS-Library-UserManual-eng.pdf` | Weintek JS object chapter | owner's Drive |
| `manual_txrail_usb_transmitter_4-20ma_v20x_g_en.pdf` | Novus TxRail-USB manual | owner's Drive |

Not found online: the ACS560 quick installation guide as an official download (the hardware
and firmware manuals cover its content), an official Weintek datasheet for the discontinued
cMT3072XH, and anything for the pressure transmitters, whose model is unknown.

The new manuals were searched for the specific facts cited above. They were not read cover to
cover.
