import pytest
from pid import PIDController
from utils import AttrDict


@pytest.fixture()
def cfg():
    return AttrDict({"kp": 1.0, "ki": 0.5, "kd": 0.1, "set_point": 10.0})


@pytest.fixture()
def pid(cfg):
    return PIDController(cfg)


# ---------------------------------------------------------------------------
# First call: dt == 0, so only proportional term fires
# ---------------------------------------------------------------------------

def test_first_call_proportional_only(pid):
    # error = 10.0 - 8.0 = 2.0; dt = 0 → integral=0, derivative=0
    out = pid.compute(8.0, 0.0)
    assert out == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Second call: integral accumulates, derivative is zero (same error)
# ---------------------------------------------------------------------------

def test_second_call_integral_accumulates(pid):
    pid.compute(8.0, 0.0)          # prime: _last_time=0, _previous_error=2.0
    out = pid.compute(8.0, 1.0)   # dt=1, error=2, integral=0.5*2=1, deriv=0
    assert out == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Third call: PV changes → derivative fires
# ---------------------------------------------------------------------------

def test_third_call_derivative(pid):
    pid.compute(8.0, 0.0)   # prime
    pid.compute(8.0, 1.0)   # build integral
    # Now PV rises to 9.0: error=1.0, prev_error=2.0
    # P=1.0, I=0.5*3.0=1.5, D=0.1*(1-2)/1=-0.1
    out = pid.compute(9.0, 2.0)
    assert out == pytest.approx(2.4)


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------

def test_reset_clears_state(pid):
    pid.compute(8.0, 0.0)
    pid.compute(8.0, 1.0)
    pid.reset()
    # After reset, behaves exactly like a first call
    out = pid.compute(8.0, 5.0)
    assert out == pytest.approx(2.0)


def test_reset_clears_integral(pid):
    pid.compute(8.0, 0.0)
    pid.compute(8.0, 1.0)  # _integral = 2.0
    pid.reset()
    assert pid._integral == 0.0
    assert pid._previous_error == 0.0
    assert pid._last_time is None


# ---------------------------------------------------------------------------
# set_cfg
# ---------------------------------------------------------------------------

def test_set_cfg_updates_all_gains(pid):
    new_cfg = AttrDict({"kp": 2.0, "ki": 1.0, "kd": 0.5, "set_point": 20.0})
    pid.set_cfg(new_cfg)
    assert pid.kp == pytest.approx(2.0)
    assert pid.ki == pytest.approx(1.0)
    assert pid.kd == pytest.approx(0.5)
    assert pid.set_point == pytest.approx(20.0)


def test_set_cfg_takes_effect_on_next_compute(pid):
    new_cfg = AttrDict({"kp": 2.0, "ki": 0.0, "kd": 0.0, "set_point": 10.0})
    pid.set_cfg(new_cfg)
    # error = 10-8 = 2, kp=2 → P = 4
    out = pid.compute(8.0, 0.0)
    assert out == pytest.approx(4.0)
