"""
The kiln firing schedule: where the "train" of zones is at any time.

    Head -> [paper] -> damper zone -> pre-heating -> firing -> cooling -> [part-open] -> [full-open] -> tail

The train moves clockwise at a constant rate. Everything outside it is the handling zone, where
rooms are unloaded and loaded with their doors open.

Position is measured by the **lead**: the (fractional) firebox number that the fire has reached.
A firebox starts firing when the lead reaches it and is fed for ``firing_hours``. Everything else
is placed relative to that: a firebox ``n`` room units ahead of the lead will start firing in
``n * hours_per_ru`` hours.

Rules and example values are from VelKilnMaster ``docs/Kiln-Domain.md`` ("Kiln Firing Schedule").
Not modelled: top-open timing and cooling fans (operator judgement) and the special damper rules
at the interconnecting flues (mentioned in the source but not written down).
"""
import math
from dataclasses import dataclass

from sim.kiln.layout import FIREBOX_COUNT, LAYOUT, Firebox, wrap

HOURS_PER_DAY = 24.0
DAMPER_SPACING_RU = 2          # dampers sit on alternate room units

ZONE_HANDLING = "handling"
ZONE_PREDRYING = "pre-drying"
ZONE_DAMPER = "damper"
ZONE_PREHEATING = "pre-heating"
ZONE_FIRING = "firing"
ZONE_COOLING = "cooling"
ZONES = (ZONE_HANDLING, ZONE_PREDRYING, ZONE_DAMPER, ZONE_PREHEATING, ZONE_FIRING, ZONE_COOLING)

DOOR_CLOSED, DOOR_PART, DOOR_OPEN = "closed", "part-open", "open"


@dataclass(frozen=True)
class Schedule:
    """Inputs of a firing schedule. Defaults are the "4.5 rooms/day" example."""
    ru_per_day: float = 9.0              # fire travel rate, room units per day
    preheat_ru: int = 6                  # room units between the damper zone and the firing zone
    damper_transition_h: float = 24.0    # time a damper takes from first lift to fully lowered
    damper_raise_in_h: float = 3.6       # inches per hour
    damper_lower_in_h: float = 2.0       # inches per hour
    damper_max_in: float = 9.0           # peak lift, inches
    charge_count: int = 160              # fuel charges per firebox
    charge_interval_h: float = 0.25      # one charge every 15 minutes
    part_open_gap_ru: int = 11           # door part-open this many units behind the last firing firebox
    full_open_gap_ru: int = 14           # door fully open this many units behind the last firing firebox
    paper_seal_ru: int = 1               # sealed, door-closed units ahead of the damper zone

    def __post_init__(self):
        if self.ru_per_day <= 0 or self.charge_count <= 0 or self.damper_max_in <= 0:
            raise ValueError("fire travel rate, charge count and damper height must be positive")
        if self.damper_raise_in_h <= 0 or self.damper_lower_in_h <= 0:
            raise ValueError("damper raise and lower rates must be positive")
        if self.damper_hold_h < 0:
            raise ValueError(
                f"damper raise ({self.damper_raise_h:.1f} h) plus lower ({self.damper_lower_h:.1f} h) "
                f"is longer than the transition time ({self.damper_transition_h:.1f} h)")
        if not 0 <= self.part_open_gap_ru <= self.full_open_gap_ru:
            raise ValueError("the part-open gap must not exceed the full-open gap")
        if self.train_length_ru >= FIREBOX_COUNT:
            raise ValueError(f"the train ({self.train_length_ru:.1f} room units) does not fit in the ring of {FIREBOX_COUNT}")

    # ------------------------------------------------------------ derived values
    @property
    def hours_per_ru(self) -> float:
        return HOURS_PER_DAY / self.ru_per_day

    @property
    def firing_hours(self) -> float:
        return self.charge_count * self.charge_interval_h

    @property
    def firing_zone_ru(self) -> float:
        return self.firing_hours / self.hours_per_ru

    @property
    def damper_zone_ru(self) -> float:
        return self.damper_transition_h / self.hours_per_ru

    @property
    def damper_raise_h(self) -> float:
        return self.damper_max_in / self.damper_raise_in_h

    @property
    def damper_lower_h(self) -> float:
        return self.damper_max_in / self.damper_lower_in_h

    @property
    def damper_hold_h(self) -> float:
        return self.damper_transition_h - self.damper_raise_h - self.damper_lower_h

    @property
    def train_length_ru(self) -> float:
        return (self.paper_seal_ru + self.damper_zone_ru + self.preheat_ru
                + self.firing_zone_ru + self.full_open_gap_ru)

    @property
    def round_days(self) -> float:
        """Days for the fire to travel once round the ring."""
        return FIREBOX_COUNT / self.ru_per_day

    # ------------------------------------------------------------ one damper's cycle
    def damper_lift_in(self, hours_since_first_lift: float) -> float:
        """Lift of a damper, in inches: raise at the raise rate, hold at the peak, lower at the lower rate."""
        t = hours_since_first_lift
        if t <= 0.0 or t >= self.damper_transition_h:
            return 0.0
        if t < self.damper_raise_h:
            return t * self.damper_raise_in_h
        if t < self.damper_raise_h + self.damper_hold_h:
            return self.damper_max_in
        return (self.damper_transition_h - t) * self.damper_lower_in_h


@dataclass(frozen=True)
class UnitState:
    """One firebox / room unit at one instant."""
    firebox: Firebox
    zone: str
    ahead_ru: float               # room units ahead of the lead (negative = the fire has passed)
    firing_hours: float | None    # hours since this firebox started firing; None when it is not firing
    charge_number: int | None     # 1..charge_count, the charge now being burnt; None when not firing
    damper_lift_in: float
    door: str
    paper_sealed: bool            # a paper seal closes the tunnel on the far (downstream) side of this unit


@dataclass(frozen=True)
class KilnState:
    time_h: float
    lead: float                   # fractional firebox number the fire has reached, 1 <= lead < 61
    units: tuple[UnitState, ...]  # index 0 is firebox 1

    def unit(self, number: int) -> UnitState:
        return self.units[wrap(number) - 1]

    def in_zone(self, zone: str) -> list[UnitState]:
        return [u for u in self.units if u.zone == zone]

    @property
    def combined_lift_in(self) -> float:
        return sum(u.damper_lift_in for u in self.units)

    @property
    def lifted_dampers(self) -> list[UnitState]:
        return [u for u in self.units if u.damper_lift_in > 0.0]


def lead_at(schedule: Schedule, time_h: float, start_lead: float = 1.0) -> float:
    """Where the fire is after ``time_h`` hours, as a fractional firebox number on the ring."""
    travelled = time_h / schedule.hours_per_ru
    return (start_lead - 1.0 + travelled) % FIREBOX_COUNT + 1.0


def _ahead(number: int, lead: float) -> float:
    """Room units from the lead to a firebox, in (-30, 30]: positive is ahead (clockwise)."""
    ahead = (number - lead) % FIREBOX_COUNT
    return ahead - FIREBOX_COUNT if ahead > FIREBOX_COUNT / 2 else ahead


def kiln_state(schedule: Schedule, time_h: float, start_lead: float = 1.0) -> KilnState:
    """Zone, damper lift, door and firing progress of every firebox at ``time_h``."""
    lead = lead_at(schedule, time_h, start_lead)
    s = schedule
    damper_head_ru = s.preheat_ru + s.damper_zone_ru           # the damper zone ends this far ahead of the lead
    # The train is longer behind the fire than half the ring, so "behind" is measured the long way round.
    units = []
    for box in LAYOUT:
        ahead = _ahead(box.number, lead)
        if ahead > damper_head_ru + s.paper_seal_ru:
            ahead -= FIREBOX_COUNT                               # it is behind the fire, not ahead of it
        hours_to_fire = ahead * s.hours_per_ru                   # negative: it lit that long ago
        firing_hours = -hours_to_fire if 0.0 <= -hours_to_fire < s.firing_hours else None
        behind_tail_ru = -ahead - s.firing_zone_ru               # room units behind the last firing firebox

        if firing_hours is not None:
            zone = ZONE_FIRING
        elif 0.0 < ahead <= s.preheat_ru:
            zone = ZONE_PREHEATING
        elif s.preheat_ru < ahead <= damper_head_ru:
            zone = ZONE_DAMPER
        elif damper_head_ru < ahead:
            zone = ZONE_PREDRYING
        elif behind_tail_ru < s.full_open_gap_ru:
            zone = ZONE_COOLING
        else:
            zone = ZONE_HANDLING

        hours_in_damper_zone = (damper_head_ru - ahead) * s.hours_per_ru
        lift = s.damper_lift_in(hours_in_damper_zone) if box.has_damper else 0.0

        if not box.has_door or zone in (ZONE_PREDRYING, ZONE_DAMPER, ZONE_PREHEATING, ZONE_FIRING):
            door = DOOR_CLOSED
        elif zone == ZONE_HANDLING:
            door = DOOR_OPEN
        else:
            door = DOOR_PART if behind_tail_ru >= s.part_open_gap_ru else DOOR_CLOSED

        charge = None if firing_hours is None else min(s.charge_count, int(firing_hours / s.charge_interval_h) + 1)
        units.append(UnitState(firebox=box, zone=zone, ahead_ru=ahead, firing_hours=firing_hours,
                               charge_number=charge, damper_lift_in=lift, door=door,
                               paper_sealed=zone == ZONE_PREDRYING and math.ceil(ahead - damper_head_ru) == s.paper_seal_ru))
    return KilnState(time_h=time_h, lead=lead, units=tuple(units))
