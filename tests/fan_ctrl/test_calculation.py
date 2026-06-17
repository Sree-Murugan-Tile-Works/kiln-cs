import math
import pytest
from calculation import Scaler, MovingAverage, calc_pv
from utils import AttrDict


# ---------------------------------------------------------------------------
# Scaler
# ---------------------------------------------------------------------------

@pytest.fixture()
def scaler():
    return Scaler(raw_min=0, raw_max=6000, eng_min=-250.0, eng_max=250.0)


def test_scaler_to_engineering_at_min(scaler):
    assert scaler.to_engineering(0) == pytest.approx(-250.0)


def test_scaler_to_engineering_at_max(scaler):
    assert scaler.to_engineering(6000) == pytest.approx(250.0)


def test_scaler_to_engineering_at_midpoint(scaler):
    assert scaler.to_engineering(3000) == pytest.approx(0.0)


def test_scaler_to_raw_at_min(scaler):
    assert scaler.to_raw(-250.0) == 0


def test_scaler_to_raw_at_max(scaler):
    assert scaler.to_raw(250.0) == 6000


def test_scaler_round_trip(scaler):
    for raw in (0, 1500, 3000, 4500, 6000):
        eng = scaler.to_engineering(raw)
        assert scaler.to_raw(eng) == raw


def test_scaler_clamp_eng_below_min(scaler):
    assert scaler.clamp_eng(-999.0) == pytest.approx(-250.0)


def test_scaler_clamp_eng_above_max(scaler):
    assert scaler.clamp_eng(999.0) == pytest.approx(250.0)


def test_scaler_clamp_eng_within_range(scaler):
    assert scaler.clamp_eng(100.0) == pytest.approx(100.0)


def test_scaler_clamp_raw_below_min(scaler):
    assert scaler.clamp_raw(-1) == 0


def test_scaler_clamp_raw_above_max(scaler):
    assert scaler.clamp_raw(9999) == 6000


def test_scaler_call_delegates_to_engineering(scaler):
    assert scaler(3000) == scaler.to_engineering(3000)


# ---------------------------------------------------------------------------
# MovingAverage
# ---------------------------------------------------------------------------

def test_moving_average_empty_returns_zero():
    ma = MovingAverage(5)
    assert ma.mean == 0.0


def test_moving_average_single_value():
    ma = MovingAverage(5)
    ma.add(10.0)
    assert ma.mean == pytest.approx(10.0)


def test_moving_average_fills_window():
    ma = MovingAverage(3)
    for v in (1.0, 2.0, 3.0):
        ma.add(v)
    assert ma.mean == pytest.approx(2.0)


def test_moving_average_evicts_oldest():
    ma = MovingAverage(3)
    for v in (1.0, 2.0, 3.0, 4.0):  # 4th add evicts 1.0
        ma.add(v)
    assert ma.mean == pytest.approx(3.0)  # (2+3+4)/3


def test_moving_average_resize_drops_excess():
    ma = MovingAverage(5)
    for v in range(5):
        ma.add(float(v))  # 0,1,2,3,4 → mean=2.0
    ma.resize(2)
    assert len(ma.q) == 2
    assert ma.mean == pytest.approx(3.5)  # last two: 3,4 → (3+4)/2


# ---------------------------------------------------------------------------
# calc_pv
# ---------------------------------------------------------------------------

@pytest.fixture()
def flow_cfg():
    return AttrDict({"c": 0.7, "a2": 0.6096, "z": 0.98128836, "r": 8.3245, "m": 89, "k": 1.4})


@pytest.fixture()
def flow_data():
    return AttrDict({"p1": 143.24, "p2": 103.0, "t": 408.0})


def test_calc_pv_returns_positive_finite(flow_cfg, flow_data):
    result = calc_pv(flow_cfg, flow_data)
    assert math.isfinite(result)
    assert result > 0


def test_calc_pv_known_values(flow_cfg, flow_data):
    # Compute expected inline using the same orifice-plate formula to catch regressions
    p2by1 = flow_data.p2 / flow_data.p1
    expected = flow_cfg.c * flow_cfg.a2 * math.sqrt(
        (2 * flow_cfg.z * flow_cfg.r * flow_data.t / flow_cfg.m) *
        (flow_cfg.k / (flow_cfg.k - 1)) *
        ((p2by1 ** (2 / flow_cfg.k)) - (p2by1 ** ((flow_cfg.k + 1) / flow_cfg.k))) *
        1000
    )
    assert calc_pv(flow_cfg, flow_data) == pytest.approx(expected)


def test_calc_pv_higher_pressure_ratio_gives_higher_flow(flow_cfg):
    data_low = AttrDict({"p1": 143.24, "p2": 103.0, "t": 408.0})
    data_high = AttrDict({"p1": 143.24, "p2": 80.0, "t": 408.0})
    assert calc_pv(flow_cfg, data_high) > calc_pv(flow_cfg, data_low)
