"""
Simulated instruments: what the controller actually sees instead of the true plant values.

``Transmitter`` models one analog channel as the CP1W-AD041 delivers it: a lagged, noisy signal
scaled to PLC counts (0..6000 over the transmitter range, signed, with 8000 meaning open circuit).
``estimate_flow`` is the controller's flow calculation from P1, P2 and T.
"""
import math
import random

from sim.gas import density

COUNTS_MIN_VALID = -300       # AD041 manual: counts run -300..6300
COUNTS_MAX_VALID = 6300
COUNTS_FULL_SCALE = 6000
COUNTS_OPEN_CIRCUIT = 8000    # AD041 reports 8000 when the loop current is below about 3.2 mA

FAULT_NONE = "none"
FAULT_OPEN = "open"           # wire break: counts read 8000
FAULT_STUCK = "stuck"         # blocked impulse line / frozen signal: counts stop changing
FAULTS = (FAULT_NONE, FAULT_OPEN, FAULT_STUCK)


class Transmitter:
    """One analog input channel: true value in, PLC counts out."""

    def __init__(self, eng_min: float, eng_max: float, tau_s: float, noise_std: float, rng: random.Random):
        self.eng_min = eng_min
        self.eng_max = eng_max
        self.tau_s = tau_s
        self.noise_std = noise_std
        self.offset = 0.0              # engineering units; drift/calibration error
        self.fault = FAULT_NONE
        self._rng = rng
        self._filtered: float | None = None
        self._last_counts = 0

    def configure(self, eng_min: float, eng_max: float, tau_s: float, noise_std: float) -> None:
        """Apply new range/lag/noise (slider moved) without losing the filter state."""
        self.eng_min, self.eng_max, self.tau_s, self.noise_std = eng_min, eng_max, tau_s, noise_std

    def sample(self, true_value: float, dt: float) -> int:
        if self.fault == FAULT_OPEN:
            return COUNTS_OPEN_CIRCUIT
        if self.fault == FAULT_STUCK:
            return self._last_counts
        if self._filtered is None:
            self._filtered = true_value
        self._filtered += (true_value - self._filtered) * (1.0 - math.exp(-dt / self.tau_s))
        measured = self._filtered + self.offset + self._rng.gauss(0.0, self.noise_std)
        span = self.eng_max - self.eng_min
        counts = round((measured - self.eng_min) / span * COUNTS_FULL_SCALE)
        self._last_counts = max(COUNTS_MIN_VALID, min(COUNTS_MAX_VALID, counts))
        return self._last_counts


def counts_valid(counts: int) -> bool:
    """False for the open-circuit code or anything outside the valid count band."""
    return COUNTS_MIN_VALID <= counts <= COUNTS_MAX_VALID


def estimate_flow(p, p1_gauge_pa: float, p2_gauge_pa: float, t_c: float) -> float:
    """
    The controller's flow in m3/s from the measured P1, P2 and T (orifice equation).

    The plate geometry is taken from the same parameters as the plant, but the controller's belief
    about Cd and the gas molar mass can be wrong (``est_*`` parameters), which is how a calibration
    or composition error shows up as a flow error. This stands in for the PLC/Pi flow calculation;
    the legacy empirical ``calc_pv`` is intentionally not used here (its units are unverified).
    """
    dp = p1_gauge_pa - p2_gauge_pa
    if dp <= 0.0:
        return 0.0
    cd = p.plate_cd * (1.0 + p.est_cd_error_pct / 100.0)
    a_bore = math.pi / 4.0 * (p.plate_beta * p.duct_diameter_m) ** 2
    rho = density(p.p_atm_pa, t_c, p.est_molar_mass_g_mol)   # same incompressible simplification as the plant
    return cd * a_bore * math.sqrt(2.0 * dp / (rho * (1.0 - p.plate_beta ** 4)))
