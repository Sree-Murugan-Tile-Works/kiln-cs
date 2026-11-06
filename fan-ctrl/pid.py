from utils import AttrDict


class PIDController:
    def __init__(self, cfg):
        self.kp = self.ki = self.kd = self.set_point = None
        self._previous_error = 0.0
        self._integral = 0.0
        self._last_time = None
        self.set_cfg(cfg)

    def set_cfg(self, cfg):
        self.kp = cfg.kp
        self.ki = cfg.ki
        self.kd = cfg.kd
        self.set_point = cfg.set_point

    def reset(self):
        self._previous_error = 0.0
        self._integral = 0.0
        self._last_time = None

    def compute(self, process_variable: float, current_time: float) -> float:
        error = self.set_point - process_variable

        if self._last_time is None:
            delta_time = 0.0
            self._last_time = current_time
        else:
            delta_time = current_time - self._last_time
            self._last_time = current_time

        proportional = self.kp * error
        self._integral += error * delta_time
        integral = self.ki * self._integral
        derivative = self.kd * (error - self._previous_error) / delta_time if delta_time > 0 else 0.0
        self._previous_error = error

        return proportional + integral + derivative


if __name__ == '__main__':
    cfg = AttrDict({"kp": 1.2, "ki": 0.05, "kd": 0.01, "set_point": 43.0})
    pid = PIDController(cfg)
    t = 0.0
    pv_sequence = [38.0, 39.5, 41.0, 42.0, 43.5, 44.0, 43.2, 42.8, 43.1, 43.0]
    print(f"{'PV':>8}  {'Error':>8}  {'Output':>10}")
    print("-" * 30)
    for pv in pv_sequence:
        out = pid.compute(pv, t)
        print(f"{pv:>8.2f}  {cfg.set_point - pv:>8.2f}  {out:>10.4f}")
        t += 1.0
