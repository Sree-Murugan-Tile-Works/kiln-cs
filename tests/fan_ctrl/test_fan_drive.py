import pytest
from fan_drive import FanDrive
from utils import AttrDict


@pytest.fixture()
def cfg():
    return AttrDict({
        "pid_min_rpm": 0,
        "pid_max_rpm": 400,
        "motor_min_rpm": 0,
        "motor_max_rpm": 450,
    })


@pytest.fixture()
def drive(cfg):
    return FanDrive(cfg)


# ---------------------------------------------------------------------------
# set_output_percent
# ---------------------------------------------------------------------------

def test_set_output_percent_zero(drive):
    drive.set_output_percent(0.0)
    assert drive.demanded_rpm == pytest.approx(0.0)
    assert drive.commanded_rpm == pytest.approx(0.0)


def test_set_output_percent_full(drive):
    drive.set_output_percent(1.0)
    assert drive.demanded_rpm == pytest.approx(400.0)
    assert drive.commanded_rpm == pytest.approx(400.0)  # within motor limits


def test_set_output_percent_half(drive):
    drive.set_output_percent(0.5)
    assert drive.demanded_rpm == pytest.approx(200.0)
    assert drive.commanded_rpm == pytest.approx(200.0)


def test_set_output_percent_clamps_to_motor_max(drive):
    drive.set_output_percent(1.5)            # demanded = 600, motor_max = 450
    assert drive.demanded_rpm == pytest.approx(600.0)
    assert drive.commanded_rpm == pytest.approx(450.0)


def test_set_output_percent_clamps_to_motor_min():
    cfg = AttrDict({"pid_min_rpm": 0, "pid_max_rpm": 400, "motor_min_rpm": 50, "motor_max_rpm": 450})
    d = FanDrive(cfg)
    d.set_output_percent(0.0)                # demanded = 0, motor_min = 50
    assert d.demanded_rpm == pytest.approx(0.0)
    assert d.commanded_rpm == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# set_rpm
# ---------------------------------------------------------------------------

def test_set_rpm_within_range(drive):
    drive.set_rpm(200)
    assert drive.commanded_rpm == pytest.approx(200.0)


def test_set_rpm_clamps_below_motor_min(drive):
    drive.set_rpm(-10)
    assert drive.commanded_rpm == pytest.approx(0.0)


def test_set_rpm_clamps_above_motor_max(drive):
    drive.set_rpm(500)
    assert drive.commanded_rpm == pytest.approx(450.0)


def test_set_rpm_at_exact_limits(drive):
    drive.set_rpm(0)
    assert drive.commanded_rpm == pytest.approx(0.0)
    drive.set_rpm(450)
    assert drive.commanded_rpm == pytest.approx(450.0)


# ---------------------------------------------------------------------------
# off()
# ---------------------------------------------------------------------------

def test_off_zeroes_both_rpms(drive):
    drive.set_rpm(300)
    drive.off()
    assert drive.commanded_rpm == 0
    assert drive.demanded_rpm == 0


# ---------------------------------------------------------------------------
# set_cfg
# ---------------------------------------------------------------------------

def test_set_cfg_changes_limits(drive):
    new_cfg = AttrDict({"pid_min_rpm": 0, "pid_max_rpm": 500, "motor_min_rpm": 100, "motor_max_rpm": 600})
    drive.set_cfg(new_cfg)
    drive.set_rpm(50)             # below new motor_min of 100
    assert drive.commanded_rpm == pytest.approx(100.0)
