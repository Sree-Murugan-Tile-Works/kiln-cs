"""
The fixed layout of the kiln: 60 fireboxes in a ring.

East battery is fireboxes 1-30, west battery 31-60. Gas and fire travel clockwise, which is the
direction of increasing firebox number (60 is followed by 1).

A room has two room units: a "mid" unit (M) and a "door" unit (D). Door units have the door and,
normally, the damper. Four units are special:

  * 1 and 31 are half rooms at the start of each battery: a damper but no door;
  * 30 (south) and 60 (north) are the interconnecting flues that join the batteries: a damper,
    but no door and no platform of tiles;
  * the door units just before them (29 and 59) have no damper.

That gives 28 doors and 30 dampers. Source: VelKilnMaster ``docs/Kiln-Domain.md`` (firebox list).
"""
from dataclasses import dataclass

FIREBOX_COUNT = 60
BATTERY_SIZE = 30
HALF_ROOMS = (1, 31)
INTERCONNECTING_FLUES = {30: "SIF", 60: "NIF"}


@dataclass(frozen=True)
class Firebox:
    number: int           # 1..60, also the thermocouple "point" number
    side: str             # "East" or "West"
    unit: str             # room-unit name, e.g. "7D", "15.5M", "SIF"
    has_door: bool
    has_damper: bool
    has_platform: bool    # False for the two interconnecting flues: no tiles there


def _firebox(number: int) -> Firebox:
    side = "East" if number <= BATTERY_SIZE else "West"
    in_battery = (number - 1) % BATTERY_SIZE + 1          # 1..30 within its battery
    room_offset = 0 if side == "East" else 14
    if number in INTERCONNECTING_FLUES:
        return Firebox(number, side, INTERCONNECTING_FLUES[number], False, True, False)
    if number in HALF_ROOMS:
        return Firebox(number, side, f"{room_offset + 1}.5M", False, True, True)
    room = room_offset + in_battery // 2
    is_door_unit = in_battery % 2 == 1
    if not is_door_unit:
        return Firebox(number, side, f"{room}M", False, False, True)
    last_door_unit = in_battery == BATTERY_SIZE - 1       # the one next to the interconnecting flue
    return Firebox(number, side, f"{room}D", True, not last_door_unit, True)


LAYOUT: tuple[Firebox, ...] = tuple(_firebox(n) for n in range(1, FIREBOX_COUNT + 1))


def firebox(number: int) -> Firebox:
    """Firebox by number; numbers wrap round the ring (61 is 1, 0 is 60)."""
    return LAYOUT[(number - 1) % FIREBOX_COUNT]


def wrap(number: int) -> int:
    """Bring any integer onto the ring 1..60."""
    return (number - 1) % FIREBOX_COUNT + 1
