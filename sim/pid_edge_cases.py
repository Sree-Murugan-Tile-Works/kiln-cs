"""
PID and fan edge-case campaign.

Runs the REAL ``fan-ctrl`` ``PIDController`` / ``FanDrive`` / ``Command`` in the simulated plant under three
controller variants, so the report can show what the daemon would do today and what a better design buys:

  prod : the control logic as ``fan-ctrl/main.py`` runs it. No output clamp on the PID, no anti-windup, no
         bumpless transfer, no PID reset on a mode change, OFF commands 0 rpm. (``ProductionLoop``)
  sim  : ``ClosedLoop`` as the GUI runs it, which patches the PID from outside (private ``_integral``).
  eng  : a prototype PID written in engineering units (m3/s in, rpm out) with output limits, back-calculation
         anti-windup, bumpless transfer, derivative on measurement and time-gap protection. (``EngLoop``)

Dev-machine only. Nothing here is site data; every plant value is a placeholder from ``sim.params``.
Run ``python -m sim.pid_edge_cases`` to print every table.
"""
import math

from sim.analysis import _quiet, _run, build, defaults, flow_at, step_metrics, TARGET_FLOW, SETTLE_BAND
from sim.instruments import counts_valid, estimate_flow, legacy_flow
from sim.loop import ClosedLoop, CHANNELS
from sim.params import make_params

from command import Command            # fan-ctrl
from fan_drive import FanDrive         # fan-ctrl
from pid import PIDController          # fan-ctrl
from utils import AttrDict             # fan-ctrl

KINDS = ("prod", "sim", "eng")
HORIZON_S = 7200


# =========================================================================== controller variants
class ProductionLoop(ClosedLoop):
    """The control logic exactly as ``fan-ctrl/main.py`` runs it (sensor-fault safe speed stays: it is PLC-side)."""

    def _control(self, counts):
        p = self.p
        self.flow_legacy = None
        if not all(counts_valid(c) for c in counts.values()):
            self.drive.set_rpm(p.safe_rpm)                 # PLC fallback; the PI's PID is simply not run
            return "SENSOR_FAULT_SAFE_RPM", None, None
        eng = {n: self._scalers()[n](counts[n]) for n in CHANNELS}
        flow = estimate_flow(p, eng["p1"], eng["p2"], eng["t"])
        self.flow_legacy = legacy_flow(eng["p1"], eng["p2"], eng["t"])
        mode = self.command.command
        if mode == "OFF":
            self.drive.off()                               # main.py: fan_drive_ctl.off() -> 0 rpm
            return "OFF_ZERO_RPM", flow, None
        if mode == "MAN":
            self.drive.set_rpm(self.command.value)
            return "MANUAL", flow, None
        span = p.flow_span_m3s
        self.pid.set_cfg(AttrDict({"kp": p.kp, "ki": p.ki, "kd": p.kd, "set_point": self.command.value / span}))
        raw = self.pid.compute(flow / span, self.time_s)
        self.drive.set_output_percent(raw)                 # main.py passes the raw PID output, unclamped
        return "PID", flow, raw


class EngPID:
    """
    PID in engineering units. Input: setpoint and measurement in m3/s. Output: fan speed in rpm.

        kp  [rpm per m3/s]      ti [s] (integral time)      td [s] (derivative time)
        u   = kp*e + I - kp*td*d(pv_filtered)/dt            I' = kp/ti*e + (u_limited - u)/tt   (back-calculation)

    * Output limited to [rpm_min, rpm_max]; ``tt`` (tracking time) unwinds the integral when limited.
    * Derivative acts on the measurement (no kick on a setpoint step) and is filtered (time ``tf``).
    * A time gap outside (0, max_dt] restarts integration instead of integrating a stale interval.
    * ``track()`` makes the next output equal a given speed (bumpless transfer).
    * A non-finite measurement holds the last output.
    """

    def __init__(self, kp, ti, td, rpm_min, rpm_max, tf_s=2.0, tt_s=None, max_dt_s=5.0):
        self.kp, self.ti, self.td, self.rpm_min, self.rpm_max = kp, ti, td, rpm_min, rpm_max
        self.tf_s, self.max_dt_s = tf_s, max_dt_s
        self.tt_s = tt_s if tt_s is not None else ti
        self._i = 0.0
        self._last_t: float | None = None
        self._last_pv: float | None = None
        self._d_filt = 0.0
        self.last_output = rpm_min

    def configure(self, kp, ti, td, rpm_min, rpm_max):
        self.kp, self.ti, self.td, self.rpm_min, self.rpm_max = kp, ti, td, rpm_min, rpm_max

    def track(self, rpm, sp, pv):
        self._i = rpm - self.kp * (sp - pv)
        self._last_t, self._last_pv, self._d_filt, self.last_output = None, pv, 0.0, rpm

    def compute(self, sp: float, pv: float, t: float) -> float:
        if not (math.isfinite(sp) and math.isfinite(pv)):
            return self.last_output
        e = sp - pv
        dt = None if self._last_t is None else t - self._last_t
        valid_dt = dt is not None and 0.0 < dt <= self.max_dt_s
        if valid_dt and self._last_pv is not None:
            alpha = dt / (self.tf_s + dt)
            self._d_filt += alpha * ((pv - self._last_pv) / dt - self._d_filt)
        elif not valid_dt:
            self._d_filt = 0.0
        unlimited = self.kp * e + self._i - self.kp * self.td * self._d_filt
        limited = min(self.rpm_max, max(self.rpm_min, unlimited))
        if valid_dt:
            self._i += dt * (self.kp / self.ti * e + (limited - unlimited) / self.tt_s)
        self._last_t, self._last_pv, self.last_output = t, pv, limited
        return limited


class EngLoop(ClosedLoop):
    """Same plant, instruments, safe-speed and mode rules as ``ClosedLoop``, but the PID is ``EngPID``."""

    def __init__(self, params=None, command="PID 3.6", seed=1):
        self.eng_pid = None
        super().__init__(params, command, seed)
        self.eng_pid = self._make_pid()

    def _make_pid(self):
        p = self.p
        kp = p.kp / p.flow_span_m3s * (p.pid_max_rpm - p.pid_min_rpm)         # rpm per m3/s, same strength as prod
        ti = p.kp / p.ki if p.ki > 0 else 1e9
        td = p.kd / p.kp if p.kp > 0 else 0.0
        return EngPID(kp, ti, td, p.motor_min_rpm, p.motor_max_rpm)

    def _control(self, counts):
        p = self.p
        self.flow_legacy = None
        if self.eng_pid is None:
            return "INIT", None, None
        if not all(counts_valid(c) for c in counts.values()):
            self._last_mode = None
            self.drive.set_rpm(p.safe_rpm)
            return "SENSOR_FAULT_SAFE_RPM", None, None
        eng = {n: self._scalers()[n](counts[n]) for n in CHANNELS}
        flow = estimate_flow(p, eng["p1"], eng["p2"], eng["t"])
        self.flow_legacy = legacy_flow(eng["p1"], eng["p2"], eng["t"])
        mode = self.command.command
        entering = mode != self._last_mode
        self._last_mode = mode
        if mode == "OFF":
            self.drive.set_rpm(p.safe_rpm)
            return "OFF_SAFE_RPM", flow, None
        if mode == "MAN":
            self.drive.set_rpm(self.command.value)
            return "MANUAL", flow, None
        kp, ti, td = (lambda q: (q.kp, q.ti, q.td))(self._make_pid())
        self.eng_pid.configure(kp, ti, td, p.motor_min_rpm, p.motor_max_rpm)
        if entering:
            self.eng_pid.track(self.drive.commanded_rpm, self.command.value, flow)
        rpm = self.eng_pid.compute(self.command.value, flow, self.time_s)
        self.drive.set_rpm(rpm)
        return "PID", flow, rpm


def make_loop(kind: str, base: dict, command: str, noisy: bool = False, **changes):
    params = build(base, **changes) if noisy else _quiet(base, **changes)
    cls = {"prod": ProductionLoop, "sim": ClosedLoop, "eng": EngLoop}[kind]
    return cls(params, command)


# =========================================================================== helpers
def _settled_at(records, target, tol=SETTLE_BAND * 2.5):
    for i, r in enumerate(records, start=1):
        if abs(r["flow_true_m3s"] - target) < tol * target:
            return float(i)
    return math.inf


def _peak_to_peak(records, key, last_s):
    tail = [r[key] for r in records if r["time_s"] > records[-1]["time_s"] - last_s and r[key] is not None]
    return max(tail) - min(tail)


def _max_step(records, key):
    return max(abs(b[key] - a[key]) for a, b in zip(records, records[1:]))


# =========================================================================== closed-loop scenarios
def unreachable_high(base, kind, hold_s=600):
    """Setpoint above what the fan can deliver for hold_s, then back to the default. Windup and recovery."""
    loop = make_loop(kind, base, "PID 6.0")
    _run(loop, hold_s)
    loop.set_command(f"PID {TARGET_FLOW}")
    recs = _run(loop, HORIZON_S)
    peak_over = max(r["flow_true_m3s"] for r in recs) / TARGET_FLOW - 1.0
    return {"recover_s": _settled_at(recs, TARGET_FLOW), "peak_over_pct": 100 * peak_over,
            "rpm_at_return": recs[0]["rpm_commanded"]}


def unreachable_low(base, kind, hold_s=600):
    """Setpoint below natural-draft flow (fan wants to stop but is held at its minimum), then default."""
    loop = make_loop(kind, base, "PID 1.0")
    _run(loop, hold_s)
    loop.set_command(f"PID {TARGET_FLOW}")
    recs = _run(loop, HORIZON_S)
    return {"recover_s": _settled_at(recs, TARGET_FLOW), "min_flow_m3s": min(r["flow_true_m3s"] for r in recs),
            "rpm_at_return": recs[0]["rpm_commanded"]}


def manual_to_pid(base, kind, man_rpm=300):
    """Switch MAN -> PID at a speed different from what the PID would choose: size of the fan kick."""
    loop = make_loop(kind, base, f"MAN {man_rpm}")
    _run(loop, 120)
    loop.set_command(f"PID {TARGET_FLOW}")
    recs = _run(loop, 300)
    return {"first_scan_jump_rpm": abs(recs[0]["rpm_commanded"] - man_rpm),
            "peak_dev_pct": 100 * max(abs(r["flow_true_m3s"] / TARGET_FLOW - 1) for r in recs[:60]),
            "settle_s": step_metrics([{**r} for r in recs], recs[0]["time_s"] - 1, flow_at(loop.p, man_rpm), TARGET_FLOW)["settle_s"]}


def pid_to_off(base, kind):
    """PID at setpoint, then OFF. The architecture says the Pi never stops the fan."""
    loop = make_loop(kind, base, f"PID {TARGET_FLOW}")
    _run(loop, 300)
    loop.set_command("OFF")
    recs = _run(loop, 120)
    return {"rpm_after_off": recs[-1]["rpm_commanded"], "flow_after_off_m3s": recs[-1]["flow_true_m3s"],
            "status": recs[-1]["status"]}


def fault_gap(base, kind, gap_s=120):
    """A sensor channel opens for gap_s then recovers. The first PID scan afterwards sees a long time gap."""
    loop = make_loop(kind, base, f"PID {TARGET_FLOW}")
    _run(loop, 300)
    loop.set_fault("p1", "open")
    _run(loop, gap_s)
    loop.set_fault("p1", "none")
    recs = _run(loop, 400)
    return {"first_rpm_jump": abs(recs[0]["rpm_commanded"] - loop.p.safe_rpm),
            "peak_dev_pct": 100 * max(abs(r["flow_true_m3s"] / TARGET_FLOW - 1) for r in recs),
            "settle_s": _settled_at(recs, TARGET_FLOW)}


def gain_change(base, kind):
    """Operator raises Kp and Ki together (config reload) while the loop sits at the setpoint."""
    loop = make_loop(kind, base, f"PID {TARGET_FLOW}")
    before = _run(loop, 600)[-1]
    loop.set_params(_quiet(base, kp=base["kp"] * 2, ki=base["ki"] * 2))
    after = _run(loop, 120)
    return {"rpm_jump": abs(after[0]["rpm_commanded"] - before["rpm_commanded"]),
            "peak_dev_pct": 100 * max(abs(r["flow_true_m3s"] / TARGET_FLOW - 1) for r in after)}


def setpoint_step(base, kind, kd=0.0, start=3.2, target=3.8, noisy=False):
    """Up-step then down-step: rise, overshoot, settle and the fan jump on the scan right after the step."""
    out = {}
    for label, a, b in (("up", start, target), ("down", target, start)):
        loop = make_loop(kind, base, f"PID {a}", noisy=noisy, kd=kd)
        _run(loop, 300)
        before = _run(loop, 1)[-1]
        loop.set_command(f"PID {b}")
        recs = _run(loop, 600)
        m = step_metrics(recs, recs[0]["time_s"] - 1, a, b)
        out[label] = {**m, "first_scan_jump_rpm": abs(recs[0]["rpm_commanded"] - before["rpm_commanded"])}
    return out


def noise_jitter(base, kind, kd, noise_pa=3.0):
    """Fan speed jitter caused by transmitter noise at a given derivative gain."""
    loop = make_loop(kind, base, f"PID {TARGET_FLOW}", noisy=True, kd=kd, p_noise_pa=noise_pa)
    recs = _run(loop, 900)[300:]
    rpms = [r["rpm_commanded"] for r in recs]
    mean = sum(rpms) / len(rpms)
    return {"rpm_std": math.sqrt(sum((x - mean) ** 2 for x in rpms) / len(rpms)),
            "rpm_step_max": _max_step(recs, "rpm_commanded")}


def unreadable_setpoint(base, kind, setpoint=2.4, run_s=1200):
    """Setpoint where P2 is under suction and the 0-250 Pa transmitter cannot read it."""
    loop = make_loop(kind, base, f"PID {setpoint}")
    recs = _run(loop, run_s)
    tail = recs[len(recs) // 2:]
    return {"true_flow_mean": sum(r["flow_true_m3s"] for r in tail) / len(tail),
            "rpm_p2p": _peak_to_peak(recs, "rpm_commanded", 600),
            "flow_p2p": _peak_to_peak(recs, "flow_true_m3s", 600),
            "est_flow_mean": sum(r["flow_estimate_m3s"] or 0.0 for r in tail) / len(tail)}


def resonance_hunt(base, kind, setpoint=2.3, run_s=1500):
    """Allow the PID to command speeds inside the 150-210 rpm resonance band (min speeds lowered to 0)."""
    loop = make_loop(kind, base, f"PID {setpoint}", motor_min_rpm=0, pid_min_rpm=0)
    recs = _run(loop, run_s)
    tail = recs[len(recs) // 2:]
    return {"time_in_band_pct": 100 * sum(r["in_resonance_band"] for r in tail) / len(tail),
            "rpm_p2p": _peak_to_peak(recs, "rpm_actual", 600),
            "rpm_mean": sum(r["rpm_actual"] for r in tail) / len(tail)}


def offset_effect(base, channel, offset):
    """Steady TRUE flow error when a transmitter reads wrong by ``offset`` (Pa or degC) and the loop holds 3.6."""
    loop = make_loop("sim", base, f"PID {TARGET_FLOW}")
    _run(loop, 300)
    loop.set_offset(channel, offset)
    last = _run(loop, 600)[-1]
    return {"true_flow": last["flow_true_m3s"], "error_pct": 100 * (last["flow_true_m3s"] / TARGET_FLOW - 1),
            "rpm": last["rpm_commanded"]}


def scan_interval_effect(base, kind, scan_s):
    loop = make_loop(kind, base, "PID 3.2", scan_interval_s=scan_s)
    _run(loop, 300)
    loop.set_command("PID 3.8")
    recs = _run(loop, 900)
    return step_metrics(recs, recs[0]["time_s"] - scan_s, 3.2, 3.8)


# =========================================================================== plant gain (units)
def plant_gain_table(base, rpms=(260, 340, 420), ambients=(10, 30, 40)):
    """d(flow)/d(rpm) in (m3/s)/rpm, and the loop gain Kp_rpm*Gp it implies. Shows why one fixed gain cannot suit all weather."""
    p0 = make_params(base)
    kp_rpm = p0.kp / p0.flow_span_m3s * (p0.pid_max_rpm - p0.pid_min_rpm)
    ki_rpm = p0.ki / p0.flow_span_m3s * (p0.pid_max_rpm - p0.pid_min_rpm)
    rows = []
    for amb in ambients:
        p = build(base, t_amb_c=amb)
        for rpm in rpms:
            gp = (flow_at(p, rpm + 5) - flow_at(p, rpm - 5)) / 10.0
            rows.append({"t_amb_c": amb, "rpm": rpm, "plant_gain": gp, "kp_loop": kp_rpm * gp, "ki_loop_per_s": ki_rpm * gp})
    return {"kp_rpm_per_m3s": kp_rpm, "ki_rpm_per_s_per_m3s": ki_rpm, "ti_s": p0.kp / p0.ki, "rows": rows}


# =========================================================================== unit-level edge cases
def _try(fn):
    try:
        return fn()
    except Exception as exc:                      # noqa: BLE001 - the point is to record what escapes
        return f"raises {type(exc).__name__}"


def pid_unit_edges():
    """Direct calls into the real PIDController with awkward numbers. Returns (case, outcome) pairs."""
    cfg = AttrDict({"kp": 1.5, "ki": 0.2, "kd": 1.0, "set_point": 0.45})
    rows = []

    def fresh():
        return PIDController(cfg)

    c = fresh(); c.compute(0.4, 100.0)
    rows.append(("repeat call, same timestamp (dt = 0)", _try(lambda: round(c.compute(0.4, 100.0), 4))))
    c = fresh(); c.compute(0.4, 100.0)
    rows.append(("clock steps backwards by 60 s (dt < 0)", _try(lambda: (c.compute(0.4, 40.0), round(c._integral, 3))[1])))
    c = fresh(); c.compute(0.4, 0.0)
    rows.append(("first scan after a 1 h gap (dt = 3600)", _try(lambda: round(c.compute(0.3, 3600.0), 3))))
    c = fresh(); c.compute(0.4, 0.0)
    rows.append(("tiny dt = 1e-6 with a 0.01 error change, kd = 1", _try(lambda: round(c.compute(0.41, 1e-6), 1))))
    c = fresh()
    rows.append(("PV is NaN", _try(lambda: c.compute(float("nan"), 1.0))))
    rows.append(("integral after the NaN", _try(lambda: c._integral)))
    c = fresh(); c.compute(float("nan"), 0.0); c.compute(0.4, 1.0)
    rows.append(("good PV after a NaN (is the loop dead?)", _try(lambda: c.compute(0.4, 2.0))))
    c = fresh()
    rows.append(("PV is None", _try(lambda: c.compute(None, 1.0))))
    c = fresh()
    rows.append(("PV is +inf", _try(lambda: c.compute(float("inf"), 1.0))))
    c = fresh(); c.compute(0.4, 0.0)
    cfg2 = AttrDict({**cfg, "set_point": 0.60}); c.set_cfg(cfg2)
    rows.append(("setpoint step 0.45 -> 0.60 with kd = 1: output on next scan", _try(lambda: round(c.compute(0.4, 1.0), 2))))
    c = fresh()
    rows.append(("integral grows with output saturated (600 s at error 0.2)",
                 _try(lambda: [c.compute(0.25, float(t)) for t in range(600)] and round(c._integral, 1))))
    c = fresh(); c.compute(0.45, 0.0)
    c._integral = 0.65 / cfg.ki                      # loop sitting at 65 % output, error 0
    before = c.compute(0.45, 1.0)
    c.set_cfg(AttrDict({"kp": 3.0, "ki": 0.4, "kd": 1.0, "set_point": 0.45}))
    rows.append(("Ki doubled while holding 65 % output (error 0): output before -> after",
                 f"{before:.2f} -> {c.compute(0.45, 2.0):.2f}"))
    return rows


def drive_unit_edges():
    """Direct calls into the real FanDrive with awkward numbers."""
    def drive(**kw):
        base = {"motor_min_rpm": 220, "motor_max_rpm": 450, "pid_min_rpm": 220, "pid_max_rpm": 450}
        return FanDrive(AttrDict({**base, **kw}))

    rows = []
    d = drive(); d.set_output_percent(0.5)
    rows.append(("set_output_percent(0.5) -> demanded / commanded", f"{d.demanded_rpm:.1f} / {d.commanded_rpm:.1f}"))
    d = drive(); d.set_output_percent(50)
    rows.append(("set_output_percent(50) (a real percent, as the name says)", f"{d.demanded_rpm:.0f} / {d.commanded_rpm:.0f}"))
    d = drive(); d.set_output_percent(-0.4)
    rows.append(("set_output_percent(-0.4)", f"{d.demanded_rpm:.1f} / {d.commanded_rpm:.1f}"))
    d = drive(); d.set_output_percent(27.0)
    rows.append(("PID raw output 27 (wound-up integral)", f"{d.demanded_rpm:.0f} / {d.commanded_rpm:.0f}"))
    d = drive(pid_min_rpm=100, pid_max_rpm=300)
    d.set_output_percent(1.0)
    rows.append(("PID range 100..300, motor range 220..450, output 1.0", f"{d.demanded_rpm:.0f} / {d.commanded_rpm:.0f}"))
    d = drive(pid_min_rpm=100, pid_max_rpm=300); d.set_output_percent(0.0)
    rows.append(("same, output 0.0 (PID range floor below motor floor)", f"{d.demanded_rpm:.0f} / {d.commanded_rpm:.0f}"))
    d = drive(motor_min_rpm=450, motor_max_rpm=220); d.set_rpm(300)
    rows.append(("motor_min 450 > motor_max 220 (misconfigured), set_rpm(300)", f"{d.commanded_rpm}"))
    d = drive()
    rows.append(("set_rpm(None)", _try(lambda: d.set_rpm(None))))
    rows.append(("set_rpm(NaN)", _try(lambda: (d.set_rpm(float("nan")), d.commanded_rpm)[1])))
    rows.append(("set_output_percent(NaN)", _try(lambda: (d.set_output_percent(float("nan")), d.commanded_rpm)[1])))
    d = drive(); d.set_rpm(300); d.off()
    rows.append(("off(): commanded rpm (Pi must never stop the fan)", f"{d.commanded_rpm}"))
    d = drive(); d.set_rpm(0)
    rows.append(("set_rpm(0) in MAN: clamped to motor_min", f"{d.commanded_rpm}"))
    d = drive(motor_min_rpm=0); d.set_rpm(180)
    rows.append(("MAN 180 rpm with motor_min 0: inside the 150-210 resonance band", f"commanded {d.commanded_rpm} (FanDrive knows nothing of the band)"))
    return rows


def command_unit_edges():
    """What ``Command`` accepts and rejects, and whether ``main.parse_cmd`` (which catches only ValueError) survives it."""
    cases = ["PID 3.6", "pid 3.6", "PID", "PID abc", "PID nan", "PID inf", "PID -5", "PID 0", "PID 3.6 junk",
             "MAN 300", "MAN 300.5", "MAN -50", "MAN 99999", "MAN 1e3", "OFF", "OFF now", "", "   ", "STOP", None]
    rows = []
    for text in cases:
        try:
            cmd = Command(text)
            outcome = f"accepted: {cmd.command} {cmd.value}"
        except ValueError as exc:
            outcome = "ValueError (parse_cmd falls back to OFF)"
        except Exception as exc:                  # noqa: BLE001
            outcome = f"{type(exc).__name__}: NOT caught by parse_cmd, daemon thread dies"
        rows.append((repr(text), outcome))
    return rows


def main_py_findings():
    """Source-level facts about fan-ctrl/main.py that the closed loop cannot show. Checked by reading the file."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "fan-ctrl" / "main.py").read_text()
    import plc
    return {
        "source_reads_class_attribute_q_avg": "plc.FlowData.q_avg" in src,
        "that_expression_at_runtime": _try(lambda: plc.FlowData.q_avg),
        "passes_raw_pid_output_to_drive": "set_output_percent(pid_out)" in src,
        "resets_pid_on_mode_change": "pid_ctrl.reset" in src,
        "off_means_zero_rpm": "fan_drive_ctl.off()" in src,
        "catches_only_valueerror": "except ValueError" in src and "IndexError" not in src,
        "cmd_value_uses_in_file": src.count("cmd.value"),     # 1 = only the MAN branch; PID setpoint is never taken from the command
    }


# =========================================================================== PID on the legacy value
class LegacyPVLoop(ProductionLoop):
    """
    What the daemon does today: the PID's process variable is the legacy ``calc_pv`` value (not m3/s) and the
    setpoint is in the same units. Gains are in "output fraction per legacy unit". If the value cannot be
    computed (P1 <= 0 or P2 outside 0..P1 - low fan speed) the daemon would raise; here the fan simply holds.
    """

    def _control(self, counts):
        if self.command.command != "PID" or not all(counts_valid(c) for c in counts.values()):
            return super()._control(counts)
        eng = {n: self._scalers()[n](counts[n]) for n in CHANNELS}
        flow = estimate_flow(self.p, eng["p1"], eng["p2"], eng["t"])
        self.flow_legacy = legacy_flow(eng["p1"], eng["p2"], eng["t"])
        if self.flow_legacy is None:
            return "LEGACY_PV_UNAVAILABLE_HOLD", flow, None
        self.pid.set_cfg(AttrDict({"kp": LEGACY_KP, "ki": LEGACY_KI, "kd": 0.0, "set_point": self.command.value}))
        raw = self.pid.compute(self.flow_legacy, self.time_s)
        self.drive.set_output_percent(raw)
        return "PID", flow, raw


LEGACY_KP, LEGACY_KI = 0.05, 0.005


def legacy_curve(base, rpms=range(220, 460, 20)):
    """Legacy value against fan speed (None = cannot be computed). Its slope changes sign."""
    from sim.plant import solve_steady
    p = make_params(base)
    out = []
    for rpm in rpms:
        op = solve_steady(p, float(rpm), p.t_gas_c, p.t_amb_c)
        out.append({"rpm": rpm, "legacy": legacy_flow(op.p1_pa, op.p2_pa, op.t_gas_c), "true_flow": op.q_m3_s})
    return out


def legacy_pv_loop(base, setpoint, run_s=900):
    """PID on the legacy value from the default 380 rpm start, warm-started. Returns where the fan ends up."""
    loop = LegacyPVLoop(_quiet(base), f"PID {setpoint}")
    # Pre-load the integral so the first output equals the 380 rpm start: otherwise the positional PID
    # starts at kp*error (about 243 rpm) and the result says more about start-up than about the loop.
    p = loop.p
    loop.pid._integral = ((p.safe_rpm - p.pid_min_rpm) / (p.pid_max_rpm - p.pid_min_rpm)) / LEGACY_KI
    recs = _run(loop, run_s)
    tail = recs[-200:]
    return {"setpoint": setpoint, "rpm_end": recs[-1]["rpm_commanded"], "rpm_min": min(r["rpm_commanded"] for r in recs),
            "rpm_max": max(r["rpm_commanded"] for r in recs), "legacy_end": recs[-1]["flow_legacy"],
            "true_flow_end": recs[-1]["flow_true_m3s"], "status_end": recs[-1]["status"],
            "unavailable_pct": 100 * sum(r["status"] == "LEGACY_PV_UNAVAILABLE_HOLD" for r in recs) / len(recs)}


def readability_scan(base, kind="sim", setpoints=(2.0, 2.4, 2.6, 2.7, 2.8, 3.0)):
    """PID setpoints around the lowest readable speed: where the loop settles, how much it hunts, and the true-vs-estimated gap."""
    rows = []
    for sp in setpoints:
        loop = make_loop(kind, base, f"PID {sp}")
        recs = _run(loop, 1500)
        tail = recs[-600:]
        rows.append({"setpoint": sp, "true_end": recs[-1]["flow_true_m3s"], "est_end": recs[-1]["flow_estimate_m3s"],
                     "rpm_end": recs[-1]["rpm_commanded"], "rpm_p2p": _peak_to_peak(recs, "rpm_commanded", 600),
                     "saturated_pct": 100 * sum(r["pressure_out_of_range"] for r in tail) / len(tail)})
    return rows


def resonance_cases(base):
    """Drive-level behaviour around the 150-210 rpm band, with the minimum speeds lowered to 0 so the band is reachable."""
    out = {}
    loop = make_loop("sim", base, "MAN 180", motor_min_rpm=0, pid_min_rpm=0)
    recs = _run(loop, 300)
    out["man_180_hold"] = {"reference_rpm": recs[-1]["rpm_drive_reference"], "actual_rpm": recs[-1]["rpm_actual"],
                           "time_in_band_pct": 100 * sum(r["in_resonance_band"] for r in recs[100:]) / len(recs[100:])}
    loop = make_loop("sim", base, "MAN 100", motor_min_rpm=0, pid_min_rpm=0)
    _run(loop, 120)
    loop.set_command("MAN 300")
    recs = _run(loop, 60)
    out["transit_100_to_300"] = {"seconds_in_band": sum(r["in_resonance_band"] for r in recs) * loop.p.scan_interval_s}
    loop = make_loop("sim", base, "MAN 300", motor_min_rpm=0, pid_min_rpm=0)
    _run(loop, 120)
    loop.set_command("OFF")                                    # sim: safe rpm, no band crossing
    loop2 = make_loop("prod", base, "MAN 300", motor_min_rpm=0, pid_min_rpm=0)
    _run(loop2, 120)
    loop2.set_command("OFF")                                   # prod: OFF = 0 rpm, so the fan coasts down THROUGH the band
    recs = _run(loop2, 60)
    out["prod_off_from_300"] = {"seconds_in_band": sum(r["in_resonance_band"] for r in recs) * loop2.p.scan_interval_s}
    return out


# =========================================================================== run everything
def run_all() -> dict:
    base = defaults()
    res = {k: {} for k in KINDS}
    for kind in KINDS:
        res[kind]["unreachable_high"] = unreachable_high(base, kind)
        res[kind]["unreachable_low"] = unreachable_low(base, kind)
        res[kind]["manual_to_pid"] = manual_to_pid(base, kind)
        res[kind]["pid_to_off"] = pid_to_off(base, kind)
        res[kind]["fault_gap"] = fault_gap(base, kind)
        res[kind]["gain_change"] = gain_change(base, kind)
        res[kind]["step"] = setpoint_step(base, kind)
        res[kind]["step_kd1"] = setpoint_step(base, kind, kd=1.0)
        res[kind]["jitter"] = {kd: noise_jitter(base, kind, kd) for kd in (0.0, 0.5, 2.0)}
        res[kind]["unreadable"] = unreadable_setpoint(base, kind)
        res[kind]["resonance"] = resonance_hunt(base, kind)
        res[kind]["scan"] = {s: scan_interval_effect(base, kind, s) for s in (0.2, 1.0, 5.0)}
    res["offsets"] = {(ch, off): offset_effect(base, ch, off)
                      for ch, off in (("p1", 5), ("p1", -5), ("p2", 5), ("p2", -5), ("t", 20), ("t", -20))}
    res["plant_gain"] = plant_gain_table(base)
    res["pid_units"] = pid_unit_edges()
    res["drive_units"] = drive_unit_edges()
    res["command_units"] = command_unit_edges()
    res["main_py"] = main_py_findings()
    res["legacy_curve"] = legacy_curve(base)
    res["legacy_pv_loop"] = [legacy_pv_loop(base, sp) for sp in (29.0, 31.0, 33.0)]
    res["readability_scan"] = readability_scan(base)
    res["resonance_cases"] = resonance_cases(base)
    return res


# =========================================================================== figures
def make_figures(outdir) -> list[str]:
    """Three PNGs for the report. Colours: prod = red, sim = grey, eng = blue."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    base = defaults()
    colours = {"prod": "#c0392b", "sim": "#7f8c8d", "eng": "#2471a3"}
    names = []

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(out / name, dpi=110)
        plt.close(fig)
        names.append(name)

    # 1. windup: setpoint above capacity for 600 s, then back to 3.6
    fig, (a, b) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    for kind in KINDS:
        loop = make_loop(kind, base, "PID 6.0")
        _run(loop, 600)
        loop.set_command(f"PID {TARGET_FLOW}")
        recs = _run(loop, 2400)
        t = [r["time_s"] - 600 for r in recs]
        a.plot(t, [r["flow_true_m3s"] for r in recs], color=colours[kind], label=kind)
        b.plot(t, [r["rpm_commanded"] for r in recs], color=colours[kind], label=kind)
    a.axhline(TARGET_FLOW, color="k", lw=0.6, ls="--")
    a.set_ylabel("true flow (m3/s)"); b.set_ylabel("commanded rpm"); b.set_xlabel("seconds after the setpoint returns to 3.6 m3/s")
    a.set_title("Windup: 10 min asking for 6.0 m3/s (fan maximum is about 4.2), then back to 3.6"); a.legend()
    save(fig, "windup.png")

    # 2. gains doubled at the setpoint
    fig, (a, b) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    for kind in ("prod", "eng"):
        loop = make_loop(kind, base, f"PID {TARGET_FLOW}")
        _run(loop, 300)
        loop.set_params(_quiet(base, kp=base["kp"] * 2, ki=base["ki"] * 2))
        recs = _run(loop, 150)
        t = [r["time_s"] - 300 for r in recs]
        a.plot(t, [r["flow_true_m3s"] for r in recs], color=colours[kind], label=kind)
        b.plot(t, [r["rpm_commanded"] for r in recs], color=colours[kind], label=kind)
    a.axhline(TARGET_FLOW, color="k", lw=0.6, ls="--")
    a.set_ylabel("true flow (m3/s)"); b.set_ylabel("commanded rpm"); b.set_xlabel("seconds after the config reload")
    a.set_title("Kp and Ki doubled at the setpoint (config reload)"); a.legend()
    save(fig, "gain_change.png")

    # 3. the legacy value is not monotonic in fan speed
    fig, a = plt.subplots(figsize=(8, 4.5))
    rows = legacy_curve(base, range(220, 460, 10))
    a.plot([r["rpm"] for r in rows if r["legacy"] is not None], [r["legacy"] for r in rows if r["legacy"] is not None],
           "o-", color=colours["prod"], label="legacy calc_pv value (left)")
    a.set_xlabel("fan speed (rpm)"); a.set_ylabel("legacy value (not m3/s)")
    c = a.twinx()
    c.plot([r["rpm"] for r in rows], [r["true_flow"] for r in rows], "s-", color=colours["eng"], label="true flow (right)")
    c.set_ylabel("true flow (m3/s)")
    a.axvspan(220, 250, color="#f5cba7", alpha=0.5)
    a.set_title("A PID on the legacy value sees the plant gain change sign above about 290 rpm")
    a.legend(loc="lower left"); c.legend(loc="upper left")
    save(fig, "legacy_vs_true.png")
    return names


if __name__ == "__main__":
    import pprint
    pprint.pprint(run_all(), width=140, sort_dicts=False)
