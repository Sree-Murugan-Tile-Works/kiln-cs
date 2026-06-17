import pytest
from command import Command


# ---------------------------------------------------------------------------
# Valid commands
# ---------------------------------------------------------------------------

def test_off_command():
    c = Command("OFF")
    assert c.command == "OFF"
    assert c.value is None


def test_pid_command():
    c = Command("PID 43.5")
    assert c.command == "PID"
    assert c.value == pytest.approx(43.5)


def test_man_command():
    c = Command("MAN 340")
    assert c.command == "MAN"
    assert c.value == 340


def test_man_value_is_int():
    c = Command("MAN 300")
    assert isinstance(c.value, int)


def test_pid_value_is_float():
    c = Command("PID 43.0")
    assert isinstance(c.value, float)


# ---------------------------------------------------------------------------
# Case and whitespace handling
# ---------------------------------------------------------------------------

def test_lowercase_input_normalised():
    c = Command("off")
    assert c.command == "OFF"


def test_mixed_case_pid():
    c = Command("pid 25.0")
    assert c.command == "PID"
    assert c.value == pytest.approx(25.0)


def test_leading_trailing_whitespace():
    c = Command("  OFF  ")
    assert c.command == "OFF"


# ---------------------------------------------------------------------------
# __str__
# ---------------------------------------------------------------------------

def test_str_off():
    assert str(Command("OFF")) == "OFF"


def test_str_pid():
    assert str(Command("PID 43.5")) == "PID:43.5"


def test_str_man():
    assert str(Command("MAN 300")) == "MAN:300"


# ---------------------------------------------------------------------------
# Invalid inputs → ValueError
# ---------------------------------------------------------------------------

def test_pid_without_value_raises():
    with pytest.raises(ValueError):
        Command("PID")


def test_man_without_value_raises():
    with pytest.raises(ValueError):
        Command("MAN")


def test_pid_with_non_numeric_raises():
    with pytest.raises(ValueError):
        Command("PID fast")


def test_man_with_float_raises():
    # int("3.14") fails
    with pytest.raises(ValueError):
        Command("MAN 3.14")


def test_unknown_command_type_raises():
    with pytest.raises(ValueError):
        Command("TURBO 100")


def test_empty_string_raises():
    with pytest.raises((ValueError, IndexError)):
        Command("")
