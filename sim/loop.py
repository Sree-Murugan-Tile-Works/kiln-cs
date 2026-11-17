"""
Closed loop: simulated plant + simulated instruments + the REAL fan-ctrl control code.

    plant --(P1, P2, T)--> transmitters --(counts)--> Scaler --> flow estimate --> PIDController
      ^                                                                              |
      +------------- rpm <-- FanDrive (clamps) <-------------------------------------+

Reused unchanged from fan-ctrl: ``PIDController``, ``FanDrive``, ``Command`` and ``Scaler``.
Behaviour that the architecture puts in the PLC (safe speed on a sensor fault, a software OFF
meaning "go to safe speed") is modelled here in ``_control`` because the Pi never stops the fan.
"""
import math
import random

from sim import params as sim_params
from sim.instruments import (Transmitter, counts_valid, counts_saturated, estimate_flow, legacy_flow,
                             COUNTS_FULL_SCALE, FAULTS)
from sim.plant import Plant, environment, kiln_area_factor, solve_steady, OperatingPoint

from calculation import Scaler          # fan-ctrl
from command import Command             # fan-ctrl
from fan_drive import FanDrive          # fan-ctrl
from pid import PIDController           # fan-ctrl
from utils import AttrDict              # fan-ctrl

MAX_PLANT_STEP_S = 0.25      # plant is integrated in steps no longer than this
CHANNELS = ("p1", "p2", "t")
DEFAULT_COMMAND = "PID 3.6"


class ClosedLoop:
    def __init__(self, params=None, command: str = DEFAULT_COMMAND, seed: int = 1):
        self.p = params if params is not None else sim_params.make_params()
        self.time_s = 0.0
        rng = random.Random(seed)
        t_amb, t_gas = environment(self.p, 0.0)
        start_rpm = min(self.p.motor_max_rpm, max(self.p.motor_min_rpm, self.p.safe_rpm))
        self.plant = Plant(self.p, start_rpm, t_gas, t_amb)
        self.transmitters = {
            "p1": Transmitter(0, 1, 1, 0, rng),
            "p2": Transmitter(0, 1, 1, 0, rng),
            "t": Transmitter(0, 1, 1, 0, rng),
        }
        self._configure_transmitters()
        self.pid = PIDController(AttrDict({"kp": 0, "ki": 0, "kd": 0, "set_point": 0}))
        self.drive = FanDrive(self._drive_cfg())
        self.drive.set_rpm(start_rpm)
        self.command = Command("OFF")
        self._last_mode: str | None = None
        self._natural_guess: float | None = None   # warm start for the "draft alone" solve
        self.drive_reference_rpm = start_rpm       # what the drive follows after skipping the resonance band
        self.flow_legacy: float | None = None      # legacy calc_pv value from the last scan (display only)
        self.set_command(command)

    # ------------------------------------------------------------ inputs
    def set_params(self, params) -> None:
        """Apply new parameters (slider moved). Plant and filter states are kept."""
        self.p = params
        self.plant.set_params(params)
        self._configure_transmitters()
        self.drive.set_cfg(self._drive_cfg())

    def set_command(self, text: str) -> None:
        """'PID <flow m3/s>', 'MAN <rpm>' or 'OFF'. An invalid string fails closed to OFF."""
        try:
            self.command = Command(text)
        except (ValueError, IndexError):
            self.command = Command("OFF")

    def set_fault(self, channel: str, fault: str) -> None:
        if channel not in CHANNELS or fault not in FAULTS:
            raise ValueError(f"channel must be one of {CHANNELS} and fault one of {FAULTS}")
        self.transmitters[channel].fault = fault

    def set_offset(self, channel: str, offset: float) -> None:
        """Calibration drift on a transmitter, in its engineering unit (Pa or degC)."""
        if channel not in CHANNELS:
            raise ValueError(f"channel must be one of {CHANNELS}")
        self.transmitters[channel].offset = offset

    # ------------------------------------------------------------ helpers
    def _drive_cfg(self) -> AttrDict:
        p = self.p
        return AttrDict({"motor_min_rpm": p.motor_min_rpm, "motor_max_rpm": p.motor_max_rpm,
                         "pid_min_rpm": p.pid_min_rpm, "pid_max_rpm": p.pid_max_rpm})

    def _configure_transmitters(self) -> None:
        p = self.p
        self.transmitters["p1"].configure(0.0, p.p_range_pa, p.sensor_tau_s, p.p_noise_pa)
        self.transmitters["p2"].configure(0.0, p.p_range_pa, p.sensor_tau_s, p.p_noise_pa)
        self.transmitters["t"].configure(0.0, p.t_range_max_c, p.sensor_tau_s, p.t_noise_c)

    def _scalers(self) -> dict[str, Scaler]:
        p = self.p
        return {"p1": Scaler(0, COUNTS_FULL_SCALE, 0.0, p.p_range_pa),
                "p2": Scaler(0, COUNTS_FULL_SCALE, 0.0, p.p_range_pa),
                "t": Scaler(0, COUNTS_FULL_SCALE, 0.0, p.t_range_max_c)}

    # ------------------------------------------------------------ control
    def _control(self, counts: dict[str, int]) -> tuple[str, float | None, float | None]:
        """
        One controller scan. Returns (status, estimated flow or None, PID output or None).
        Updates ``self.drive``.
        """
        p = self.p
        self.flow_legacy = None
        if not all(counts_valid(c) for c in counts.values()):
            self.pid.reset()
            self._last_mode = None
            self.drive.set_rpm(p.safe_rpm)
            return "SENSOR_FAULT_SAFE_RPM", None, None

        scalers = self._scalers()
        eng = {name: scalers[name](counts[name]) for name in CHANNELS}
        flow = estimate_flow(p, eng["p1"], eng["p2"], eng["t"])
        self.flow_legacy = legacy_flow(eng["p1"], eng["p2"], eng["t"])

        mode = self.command.command
        entering_pid = mode == "PID" and self._last_mode != "PID"
        if mode != self._last_mode:
            self.pid.reset()
            self._last_mode = mode

        if mode == "OFF":
            self.drive.set_rpm(p.safe_rpm)      # the Pi never stops the fan: OFF means safe speed
            return "OFF_SAFE_RPM", flow, None
        if mode == "MAN":
            self.drive.set_rpm(self.command.value)
            return "MANUAL", flow, None

        span = p.flow_span_m3s
        self.pid.set_cfg(AttrDict({"kp": p.kp, "ki": p.ki, "kd": p.kd,
                                   "set_point": self.command.value / span}))
        if entering_pid:
            self._bumpless_start(flow / span)
        raw = self.pid.compute(flow / span, self.time_s)
        self.drive.set_output_percent(max(0.0, min(1.0, raw)))
        self._anti_windup(raw)
        return "PID", flow, raw

    def _bumpless_start(self, pv_normalised: float) -> None:
        """
        Start the PID at the fan speed it is already running at instead of at zero, so switching into
        PID (or recovering from a sensor fault) does not kick the fan. ``PIDController`` is positional
        with no bumpless transfer, so the integral term is pre-loaded here (simulation-side only):
        first output = kp*error + ki*integral = current speed as a fraction of the PID range.
        """
        p = self.p
        if p.ki <= 0.0 or p.pid_max_rpm <= p.pid_min_rpm:
            return
        fraction = (self.drive.commanded_rpm - p.pid_min_rpm) / (p.pid_max_rpm - p.pid_min_rpm)
        fraction = max(0.0, min(1.0, fraction))
        error = self.pid.set_point - pv_normalised
        self.pid._integral = (fraction - p.kp * error) / p.ki

    def _anti_windup(self, raw: float) -> None:
        """
        Conditional integration: if the fan is at a speed limit and the error still pushes into it,
        undo this scan's integral accumulation. The real PIDController has no anti-windup of its
        own, so this touches its private ``_integral`` / ``_previous_error`` on purpose
        (simulation-side only). After ``compute()`` the controller's ``_previous_error`` is the
        error it just used.
        """
        if self.p.anti_windup < 0.5:
            return
        error = self.pid._previous_error
        at_high_limit = raw > 1.0 or self.drive.demanded_rpm > self.drive.commanded_rpm
        at_low_limit = raw < 0.0 or self.drive.demanded_rpm < self.drive.commanded_rpm
        if (at_high_limit and error > 0.0) or (at_low_limit and error < 0.0):
            self.pid._integral -= error * self.p.scan_interval_s

    def _skip_resonance(self, rpm: float) -> float:
        """
        The drive's critical-speed function. A reference inside the resonance band is not followed:
        the drive stays at the edge it arrived from, and jumps across only when the reference leaves
        the band on the other side. The shaft still passes through the band while ramping.
        """
        low, high = self.p.resonance_low_rpm, self.p.resonance_high_rpm
        if high <= low or not low < rpm < high:
            return rpm
        if self.drive_reference_rpm <= low:
            return low
        if self.drive_reference_rpm >= high:
            return high
        return low if rpm - low < high - rpm else high

    # ------------------------------------------------------------ stepping
    def step(self) -> dict:
        """Advance one controller scan and return a record of everything, for logging/plotting."""
        p = self.p
        dt = p.scan_interval_s
        t_amb, t_gas_target = environment(p, self.time_s)
        area_factor = kiln_area_factor(p, self.time_s)
        self.drive_reference_rpm = self._skip_resonance(self.drive.commanded_rpm)

        sub_steps = max(1, math.ceil(dt / MAX_PLANT_STEP_S))
        op: OperatingPoint | None = None
        for _ in range(sub_steps):
            op = self.plant.step(dt / sub_steps, self.drive_reference_rpm, t_gas_target, t_amb, area_factor)
        self.time_s += dt

        counts = {"p1": self.transmitters["p1"].sample(op.p1_pa, dt),
                  "p2": self.transmitters["p2"].sample(op.p2_pa, dt),
                  "t": self.transmitters["t"].sample(op.t_gas_c, dt)}
        status, flow_estimate, pid_raw = self._control(counts)

        natural = solve_steady(p, 0.0, self.plant.t_gas_c, t_amb, guess=self._natural_guess,
                               kiln_area_factor=area_factor)
        self._natural_guess = natural.mass_flow_kg_s
        return {
            "time_s": self.time_s,
            "status": status,
            "mode": self.command.command,
            "setpoint_m3s": self.command.value if self.command.command == "PID" else None,
            "flow_estimate_m3s": flow_estimate,
            "flow_legacy": self.flow_legacy,
            "flow_true_m3s": op.q_m3_s,
            "flow_natural_only_m3s": natural.q_m3_s,
            "rpm_commanded": self.drive.commanded_rpm,
            "rpm_drive_reference": self.drive_reference_rpm,
            "rpm_actual": self.plant.rpm,
            "in_resonance_band": p.resonance_low_rpm < self.plant.rpm < p.resonance_high_rpm,
            "pressure_out_of_range": counts_saturated(counts["p1"]) or counts_saturated(counts["p2"]),
            "kiln_area_factor": area_factor,
            "pid_output": pid_raw,
            "p1_pa": op.p1_pa, "p2_pa": op.p2_pa, "plate_dp_pa": op.plate_dp_pa,
            "p_fan_in_pa": op.p_fan_in_pa, "p_fan_out_pa": op.p_fan_out_pa,
            "p_chimney_base_pa": op.p_chimney_base_pa,
            "draft_pa": op.draft_pa, "fan_dp_pa": op.fan_dp_pa,
            "t_gas_c": op.t_gas_c, "t_ambient_c": t_amb,
            "t_chimney_mean_c": op.t_chimney_mean_c, "t_chimney_top_c": op.t_chimney_top_c,
            "counts_p1": counts["p1"], "counts_p2": counts["p2"], "counts_t": counts["t"],
            "stalled": op.stalled,
        }
