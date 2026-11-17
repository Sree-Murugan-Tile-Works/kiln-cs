"""
Web GUI backend for the kiln simulation.

A background thread steps the closed loop (``sim.loop.ClosedLoop``) faster than real time and keeps
a rolling history. The browser only draws: sliders are built from the parameter registry, every
change is validated here, and all numbers come from the simulation.

A second page, ``/kiln``, shows the whole-kiln model (stage 2) from its own runner
(``sim.kiln_runner.KilnRunner``) with its own ``/api/kiln/...`` routes.

Run:  python -m sim.server            (from the repo root, venv active)
Then open http://127.0.0.1:5002 (exhaust path) or http://127.0.0.1:5002/kiln (whole kiln)
"""
import argparse
import threading
from collections import deque
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from sim.instruments import FAULTS
from sim.kiln_runner import KilnRunner
from sim.loop import ClosedLoop, CHANNELS, DEFAULT_COMMAND
from sim.params import make_params, params_to_dict, specs_as_dicts

HISTORY_SCANS = 3600            # rolling history kept for the browser (1 h at a 1 s scan)
WALL_TICK_S = 0.1               # how often the runner thread wakes
MAX_SCANS_PER_TICK = 300        # safety cap so a high speed cannot starve the server
SPEEDS = (1, 5, 20, 60, 200)    # simulated seconds per wall-clock second offered in the GUI
DEFAULT_SPEED = 5
DEFAULT_PORT = 5002
STATIC_DIR = Path(__file__).resolve().parent / "static"


class SimRunner:
    """Owns the loop, the slider values and the history; safe to call from Flask threads."""

    def __init__(self, autostart: bool = True):
        self._lock = threading.RLock()
        self.values = params_to_dict(make_params())
        self.command_text = DEFAULT_COMMAND
        self.running = True
        self.speed = DEFAULT_SPEED
        self.history: deque[dict] = deque(maxlen=HISTORY_SCANS)
        self._carry = 0.0
        self._stop = threading.Event()
        self._build_loop()
        self._thread: threading.Thread | None = None
        if autostart:
            self._thread = threading.Thread(target=self._run, name="sim-runner", daemon=True)
            self._thread.start()

    # ------------------------------------------------------------------ internals
    def _build_loop(self) -> None:
        self.loop = ClosedLoop(make_params(self.values), self.command_text)
        self.faults = {c: "none" for c in CHANNELS}
        self.offsets = {c: 0.0 for c in CHANNELS}
        self.history.clear()
        self._carry = 0.0

    def _run(self) -> None:
        while not self._stop.wait(WALL_TICK_S):
            with self._lock:
                if not self.running:
                    continue
                self._carry += self.speed * WALL_TICK_S / self.loop.p.scan_interval_s
                scans = min(int(self._carry), MAX_SCANS_PER_TICK)
                self._carry = 0.0 if scans == MAX_SCANS_PER_TICK else self._carry - scans
                self.advance(scans)

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ actions
    def advance(self, scans: int) -> None:
        with self._lock:
            for _ in range(scans):
                self.history.append(self.loop.step())

    def update_params(self, changes: dict) -> None:
        """Raises ValueError for unknown names or out-of-range values; nothing is changed then."""
        with self._lock:
            merged = {**self.values, **{k: float(v) for k, v in changes.items()}}
            params = make_params(merged)
            self.values = merged
            self.loop.set_params(params)

    def reset_params(self) -> None:
        with self._lock:
            self.values = params_to_dict(make_params())
            self.loop.set_params(make_params(self.values))

    def set_command(self, text: str) -> None:
        with self._lock:
            self.command_text = text
            self.loop.set_command(text)

    def set_fault(self, channel: str, fault: str) -> None:
        with self._lock:
            self.loop.set_fault(channel, fault)
            self.faults[channel] = fault

    def set_offset(self, channel: str, offset: float) -> None:
        with self._lock:
            self.loop.set_offset(channel, offset)
            self.offsets[channel] = offset

    def control(self, action: str, speed: float | None = None) -> None:
        with self._lock:
            if speed is not None:
                if speed not in SPEEDS:
                    raise ValueError(f"speed must be one of {SPEEDS}")
                self.speed = speed
            if action == "pause":
                self.running = False
            elif action == "run":
                self.running = True
            elif action == "reset":
                self._build_loop()
            elif action != "none":
                raise ValueError(f"unknown action '{action}'")

    def snapshot(self, since: float = -1.0) -> dict:
        with self._lock:
            return {
                "running": self.running, "speed": self.speed, "speeds": list(SPEEDS),
                "command": self.command_text, "faults": dict(self.faults),
                "offsets": dict(self.offsets), "values": dict(self.values),
                "time_s": self.loop.time_s,
                "records": [r for r in self.history if r["time_s"] > since],
                # The picture needs the whole path, but only for the latest instant, so it is
                # built here and not stored with every history record.
                "profile": self.loop.profile(),
            }


def create_app(autostart: bool = True) -> Flask:
    app = Flask(__name__, static_folder=None)
    runner = SimRunner(autostart=autostart)
    app.config["RUNNER"] = runner

    def bad_request(message: str):
        return jsonify({"error": message}), 400

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC_DIR, name)

    @app.get("/api/specs")
    def specs():
        return jsonify({"specs": specs_as_dicts(), "defaults": params_to_dict(make_params()),
                        "channels": list(CHANNELS), "faults": list(FAULTS)})

    @app.get("/api/state")
    def state():
        return jsonify(runner.snapshot(since=request.args.get("since", default=-1.0, type=float)))

    @app.post("/api/params")
    def post_params():
        body = request.get_json(silent=True) or {}
        if body.get("reset") is True:
            runner.reset_params()
        else:
            try:
                runner.update_params(body)
            except (ValueError, TypeError) as exc:
                return bad_request(str(exc))
        return jsonify({"values": runner.snapshot()["values"]})

    @app.post("/api/command")
    def post_command():
        text = str((request.get_json(silent=True) or {}).get("text", ""))
        runner.set_command(text)
        return jsonify({"command": runner.command_text})

    @app.post("/api/fault")
    def post_fault():
        body = request.get_json(silent=True) or {}
        try:
            if "fault" in body:
                runner.set_fault(body.get("channel"), body["fault"])
            if "offset" in body:
                runner.set_offset(body.get("channel"), float(body["offset"]))
        except (ValueError, TypeError) as exc:
            return bad_request(str(exc))
        return jsonify({"faults": runner.faults, "offsets": runner.offsets})

    @app.post("/api/control")
    def post_control():
        body = request.get_json(silent=True) or {}
        try:
            runner.control(body.get("action", "none"), body.get("speed"))
        except ValueError as exc:
            return bad_request(str(exc))
        return jsonify({"running": runner.running, "speed": runner.speed})

    # ------------------------------------------------------------------ kiln page (stage 2)
    kiln = KilnRunner(autostart=autostart)
    app.config["KILN_RUNNER"] = kiln

    @app.get("/kiln")
    def kiln_page():
        return send_from_directory(STATIC_DIR, "kiln.html")

    @app.get("/api/kiln/state")
    def kiln_state():
        return jsonify(kiln.snapshot(since=request.args.get("since", default=-1.0, type=float)))

    @app.post("/api/kiln/params")
    def kiln_params():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return bad_request("expected a JSON object of control values")
        try:
            kiln.set_controls(body)
        except (ValueError, TypeError) as exc:
            return bad_request(str(exc))
        return jsonify({"controls": kiln.controls})

    @app.post("/api/kiln/upset")
    def kiln_upset():
        body = request.get_json(silent=True) or {}
        try:
            result = kiln.upset(body)
        except (ValueError, TypeError) as exc:
            return bad_request(str(exc))
        return jsonify({"ok": True, **result})

    @app.post("/api/kiln/control")
    def kiln_control():
        body = request.get_json(silent=True) or {}
        try:
            kiln.control(body.get("action", "none"), body.get("speed"))
        except ValueError as exc:
            return bad_request(str(exc))
        return jsonify({"running": kiln.running, "speed": kiln.speed})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Kiln process simulation GUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    app = create_app()
    print(f"Kiln simulation GUI on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
