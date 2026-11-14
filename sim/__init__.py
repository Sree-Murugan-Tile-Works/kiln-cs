"""
Kiln process simulation: parametric plant (natural draft, chimney, orifice plate, fan) plus the
real fan-ctrl control code in a closed loop. Dev-machine only; no hardware involved.
"""
import sys
from pathlib import Path

# The control code under test lives in fan-ctrl/ (flat modules: pid, fan_drive, command, ...).
_FAN_CTRL_DIR = str(Path(__file__).resolve().parent.parent / "fan-ctrl")
if _FAN_CTRL_DIR not in sys.path:
    sys.path.insert(0, _FAN_CTRL_DIR)
