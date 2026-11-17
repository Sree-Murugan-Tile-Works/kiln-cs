import pytest

from sim.kiln.layout import LAYOUT, FIREBOX_COUNT, firebox, wrap
from sim.kiln.schedule import (Schedule, kiln_state, lead_at, ZONES, ZONE_HANDLING, ZONE_PREDRYING, ZONE_DAMPER,
                               ZONE_PREHEATING, ZONE_FIRING, ZONE_COOLING, DOOR_CLOSED, DOOR_PART, DOOR_OPEN)


# --------------------------------------------------------------------------- layout
def test_ring_has_60_fireboxes_in_two_batteries():
    assert len(LAYOUT) == FIREBOX_COUNT == 60
    assert [b.number for b in LAYOUT] == list(range(1, 61))
    assert sum(b.side == "East" for b in LAYOUT) == 30 and sum(b.side == "West" for b in LAYOUT) == 30


def test_door_and_damper_counts_match_the_site():
    assert sum(b.has_door for b in LAYOUT) == 28
    assert sum(b.has_damper for b in LAYOUT) == 30
    assert sum(b.has_platform for b in LAYOUT) == 58


@pytest.mark.parametrize("number, unit, door, damper, platform", [
    (1, "1.5M", False, True, True),      # half room: damper, no door
    (2, "1M", False, False, True),
    (3, "1D", True, True, True),
    (15, "7D", True, True, True),
    (29, "14D", True, False, True),      # door unit next to the interconnecting flue: no damper
    (30, "SIF", False, True, False),     # south interconnecting flue: no tiles
    (31, "15.5M", False, True, True),
    (53, "25D", True, True, True),
    (59, "28D", True, False, True),
    (60, "NIF", False, True, False),
])
def test_known_fireboxes(number, unit, door, damper, platform):
    box = firebox(number)
    assert (box.unit, box.has_door, box.has_damper, box.has_platform) == (unit, door, damper, platform)


def test_numbers_wrap_round_the_ring():
    assert wrap(61) == 1 and wrap(0) == 60 and wrap(60) == 60
    assert firebox(61) is firebox(1)


# --------------------------------------------------------------------------- schedule: derived values
def test_derived_values_match_the_schedule_document():
    s = Schedule()
    assert s.hours_per_ru == pytest.approx(2.667, abs=0.001)
    assert s.firing_hours == 40
    assert s.firing_zone_ru == pytest.approx(15)
    assert s.damper_zone_ru == pytest.approx(9)
    assert s.damper_hold_h == pytest.approx(17)
    assert s.train_length_ru == pytest.approx(45)
    assert s.round_days == pytest.approx(6.67, abs=0.01)


@pytest.mark.parametrize("changes", [
    {"damper_transition_h": 5},           # raise + lower alone take 7 h
    {"ru_per_day": 0},
    {"part_open_gap_ru": 20},             # beyond the full-open gap
    {"full_open_gap_ru": 40},             # train longer than the ring
    {"damper_raise_in_h": 0},
])
def test_invalid_schedules_are_rejected(changes):
    with pytest.raises(ValueError):
        Schedule(**changes)


def test_damper_cycle_raises_holds_and_lowers():
    s = Schedule()
    assert s.damper_lift_in(-1) == 0 and s.damper_lift_in(0) == 0
    assert s.damper_lift_in(1.0) == pytest.approx(3.6)
    assert s.damper_lift_in(2.5) == pytest.approx(9.0)
    assert s.damper_lift_in(10) == 9.0
    assert s.damper_lift_in(19.5) == pytest.approx(9.0)
    assert s.damper_lift_in(22.0) == pytest.approx(4.0)       # 2 h left at 2 in/h
    assert s.damper_lift_in(24) == 0 and s.damper_lift_in(30) == 0


# --------------------------------------------------------------------------- the train
def test_fire_travels_at_the_scheduled_rate_and_wraps():
    s = Schedule()
    assert lead_at(s, 0, start_lead=10) == pytest.approx(10)
    assert lead_at(s, 24, start_lead=10) == pytest.approx(19)                # 9 room units per day
    assert lead_at(s, s.round_days * 24, start_lead=10) == pytest.approx(10)  # once round the ring
    assert lead_at(s, 24 * 6, start_lead=10) == pytest.approx(4)             # 54 units on: past 60, back to 4


def test_zones_appear_in_train_order_round_the_ring():
    state = kiln_state(Schedule(), 0, start_lead=30.5)
    zones = [state.unit(n).zone for n in range(31, 31 + 60)]      # walk clockwise, starting just ahead of the fire
    order = [z for i, z in enumerate(zones) if i == 0 or z != zones[i - 1]]
    assert order == [ZONE_PREHEATING, ZONE_DAMPER, ZONE_PREDRYING, ZONE_HANDLING, ZONE_COOLING, ZONE_FIRING]
    assert set(zones) == set(ZONES)


def test_zone_widths_match_the_schedule():
    state = kiln_state(Schedule(), 0, start_lead=30.5)
    counts = {zone: len(state.in_zone(zone)) for zone in ZONES}
    assert counts == {ZONE_FIRING: 15, ZONE_PREHEATING: 6, ZONE_DAMPER: 9, ZONE_PREDRYING: 1,
                      ZONE_COOLING: 14, ZONE_HANDLING: 15}


def test_about_fifteen_fireboxes_fire_at_once_at_any_time():
    s = Schedule()
    for hour in range(0, 200, 7):
        assert len(kiln_state(s, hour).in_zone(ZONE_FIRING)) in (15, 16)


def test_firing_progress_and_charge_number():
    s = Schedule()
    state = kiln_state(s, 0, start_lead=20.0)
    newest, oldest = state.unit(20), state.unit(6)
    assert newest.firing_hours == pytest.approx(0) and newest.charge_number == 1
    assert oldest.firing_hours == pytest.approx(14 * s.hours_per_ru)
    assert oldest.charge_number == 150                    # 37.33 h at one charge per 15 minutes
    assert state.unit(5).firing_hours is None             # lit 40 h ago: finished
    assert state.unit(21).firing_hours is None            # not yet lit


def test_a_firebox_goes_through_the_zones_in_order_as_the_train_passes():
    s = Schedule()
    seen = []
    for step in range(0, int(s.round_days * 24 * 4)):
        zone = kiln_state(s, step / 4, start_lead=1.0).unit(25).zone
        if not seen or seen[-1] != zone:
            seen.append(zone)
    assert seen == [ZONE_HANDLING, ZONE_PREDRYING, ZONE_DAMPER, ZONE_PREHEATING, ZONE_FIRING, ZONE_COOLING, ZONE_HANDLING]


# --------------------------------------------------------------------------- dampers
def test_four_or_five_dampers_are_lifted_away_from_the_corners():
    s = Schedule()
    for lead in (4.0, 5.3, 6.9, 8.1, 9.6):                 # damper zone on the east side, clear of the flues
        lifted = kiln_state(s, 0, start_lead=lead).lifted_dampers
        assert len(lifted) in (4, 5)
        assert all(u.zone == ZONE_DAMPER and u.firebox.has_damper for u in lifted)


def test_combined_lift_stays_roughly_constant_away_from_the_corners():
    s = Schedule()
    totals = [kiln_state(s, hour / 2, start_lead=3.0).combined_lift_in for hour in range(0, 30)]   # 15 h
    assert min(totals) > 30 and max(totals) < 42
    assert (max(totals) - min(totals)) / max(totals) < 0.25


def test_only_units_with_a_damper_are_lifted():
    state = kiln_state(Schedule(), 0, start_lead=10.0)
    assert all(u.firebox.has_damper for u in state.lifted_dampers)
    assert all(u.damper_lift_in == 0 for u in state.units if u.zone != ZONE_DAMPER)


def test_damper_nearest_the_fire_is_lowering_and_the_far_one_is_rising():
    state = kiln_state(Schedule(), 0, start_lead=4.4)
    lifted = sorted(state.lifted_dampers, key=lambda u: u.ahead_ru)
    assert lifted[0].damper_lift_in < 9.0                  # about to close: full gas flow passes it
    assert max(u.damper_lift_in for u in lifted) == 9.0    # the ones in the middle are held at the peak


# --------------------------------------------------------------------------- doors and paper
def test_doors_open_in_stages_behind_the_fire():
    s = Schedule()
    state = kiln_state(s, 0, start_lead=45.5)
    tail = 45 - 15                                         # last firebox still firing is 31; 30 just finished
    doors = {n: state.unit(n).door for n in range(1, 61)}
    assert doors[wrap(tail - 7)] == DOOR_CLOSED            # 23: hot, just behind the fire
    assert doors[wrap(tail - 11)] == DOOR_PART             # 19: part-open gap reached
    assert doors[wrap(tail - 15)] == DOOR_OPEN             # 15: handling
    assert all(doors[n] == DOOR_CLOSED for n in range(31, 61) if state.unit(n).zone != ZONE_HANDLING)


def test_units_without_a_door_are_always_closed():
    for lead in (1.0, 17.5, 33.2, 51.9):
        state = kiln_state(Schedule(), 0, start_lead=lead)
        assert all(u.door == DOOR_CLOSED for u in state.units if not u.firebox.has_door)


def test_one_paper_seal_sits_at_the_head_of_the_train():
    state = kiln_state(Schedule(), 0, start_lead=20.5)
    sealed = [u for u in state.units if u.paper_sealed]
    assert len(sealed) == 1
    assert sealed[0].zone == ZONE_PREDRYING
    assert state.unit(sealed[0].firebox.number + 1).zone == ZONE_HANDLING
    assert state.unit(sealed[0].firebox.number - 1).zone == ZONE_DAMPER


def test_handling_zone_is_about_a_quarter_of_the_ring():
    for hour in range(0, 160, 11):
        assert len(kiln_state(Schedule(), hour).in_zone(ZONE_HANDLING)) in (14, 15, 16)


def test_faster_schedule_stretches_the_firing_zone():
    fast = Schedule(ru_per_day=10.0, full_open_gap_ru=12)
    assert fast.firing_zone_ru == pytest.approx(16.67, abs=0.01)
    assert len(kiln_state(fast, 0, start_lead=30.5).in_zone(ZONE_FIRING)) == 17
