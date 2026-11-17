"""
Background runner for the kiln page (``/kiln``).

Like ``sim.server.SimRunner`` for the exhaust page: a thread steps ``KilnSim`` much faster than
real time and keeps a rolling history; Flask threads call the methods below, all under one lock.
The browser only draws what ``snapshot`` returns.
"""
import threading
from collections import deque

from sim.kiln.kilnsim import KilnSim

KILN_DT_S = 300.0               # simulated seconds per kiln step (stage H shows 300 s matches 60 s closely)
KILN_HISTORY_STEPS = 2016       # one simulated week at 300 s
KILN_SPEEDS = (600, 3600, 21600)        # simulated seconds per wall second: 10 min/s, 1 h/s, 6 h/s
KILN_SPEED_LABELS = {600: "10 min/s", 3600: "1 h/s", 21600: "6 h/s"}
KILN_DEFAULT_SPEED = 3600
WALL_TICK_S = 0.1
MAX_STEPS_PER_TICK = 20         # keeps the server responsive if a step is slow
CONTROL_NAMES = ("rpm", "ru_per_day", "fuel_moisture", "charge_size_factor", "t_amb_c")


class KilnRunner:
    """Owns a ``KilnSim``, the operator controls and the history; safe to call from Flask threads."""

    def __init__(self, autostart: bool = True):
        self._lock = threading.RLock()
        self.controls = {"rpm": 380.0, "ru_per_day": 9.0, "fuel_moisture": 0.22,
                         "charge_size_factor": 1.0, "t_amb_c": 30.0}
        self.running = True
        self.speed = KILN_DEFAULT_SPEED
        self.history: deque[dict] = deque(maxlen=KILN_HISTORY_STEPS)
        self._carry = 0.0
        self._stop = threading.Event()
        self._build()
        self._thread: threading.Thread | None = None
        if autostart:
            self._thread = threading.Thread(target=self._run, name="kiln-runner", daemon=True)
            self._thread.start()

    # ------------------------------------------------------------------ internals
    def _build(self) -> None:
        sim = KilnSim(dt_s=KILN_DT_S, rpm=self.controls["rpm"], t_amb_c=self.controls["t_amb_c"],
                      fuel_moisture=self.controls["fuel_moisture"],
                      charge_size_factor=self.controls["charge_size_factor"])
        if self.controls["ru_per_day"] != sim.schedule.ru_per_day:
            sim.set_travel_rate(self.controls["ru_per_day"])
        self.sim = sim
        self.history.clear()
        self._carry = 0.0
        self.history.append(sim.step())         # one step so the page has something to draw at once

    def _run(self) -> None:
        while not self._stop.wait(WALL_TICK_S):
            with self._lock:
                if not self.running:
                    continue
                self._carry += self.speed * WALL_TICK_S / self.sim.dt_s
                steps = min(int(self._carry), MAX_STEPS_PER_TICK)
                self._carry = 0.0 if steps == MAX_STEPS_PER_TICK else self._carry - steps
                self.advance(steps)

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ actions
    def advance(self, steps: int) -> None:
        with self._lock:
            for _ in range(steps):
                self.history.append(self.sim.step())

    def set_controls(self, changes: dict) -> None:
        """Apply operator controls. Raises ValueError (nothing changed) for unknown names or bad values."""
        unknown = set(changes) - set(CONTROL_NAMES)
        if unknown:
            raise ValueError(f"unknown control(s): {sorted(unknown)}")
        values = {name: float(value) for name, value in changes.items()}
        with self._lock:
            setters = {"rpm": self.sim.set_rpm, "t_amb_c": self.sim.set_ambient,
                       "fuel_moisture": self.sim.set_moisture, "charge_size_factor": self.sim.set_charge_factor,
                       "ru_per_day": self.sim.set_travel_rate}
            old = dict(self.controls)
            try:
                for name, value in values.items():
                    setters[name](value)
                    self.controls[name] = value
            except ValueError:
                for name in values:                              # undo the ones already applied
                    if old[name] != self.controls[name]:
                        setters[name](old[name])
                self.controls = old
                raise

    def upset(self, body: dict) -> dict:
        """Operator upsets: skip charges, hold a damper, open a door early, or clear them all."""
        kind = body.get("type")
        with self._lock:
            if kind == "skip":
                return {"units": self.sim.skip_charges(_whole(body.get("count")))}
            if kind == "damper":
                lift = body.get("lift_in")
                self.sim.override_damper(_whole(body.get("unit")), None if lift is None else float(lift))
            elif kind == "door":
                self.sim.override_door(_whole(body.get("unit")), body.get("door"))
            elif kind == "clear":
                self.sim.clear_upsets()
            else:
                raise ValueError("upset type must be 'skip', 'damper', 'door' or 'clear'")
            return {}

    def control(self, action: str, speed: float | None = None) -> None:
        with self._lock:
            if speed is not None:
                if speed not in KILN_SPEEDS:
                    raise ValueError(f"speed must be one of {KILN_SPEEDS}")
                self.speed = int(speed)
            if action == "pause":
                self.running = False
            elif action == "run":
                self.running = True
            elif action == "reset":
                self._build()
            elif action != "none":
                raise ValueError(f"unknown action '{action}'")

    def snapshot(self, since: float = -1.0) -> dict:
        with self._lock:
            kiln = self.sim.snapshot()
            return {
                "running": self.running, "speed": self.speed,
                "speeds": [{"value": s, "label": KILN_SPEED_LABELS[s]} for s in KILN_SPEEDS],
                "dt_s": self.sim.dt_s, "time_s": self.sim.time_s, "controls": dict(self.controls),
                "records": [r for r in self.history if r["time_s"] > since],
                "kiln": kiln,
            }


def _whole(value) -> int:
    """A whole number from JSON (5 or 5.0), else ValueError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != int(value):
        raise ValueError("expected a whole number")
    return int(value)
