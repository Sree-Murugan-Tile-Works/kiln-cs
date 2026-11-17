import random

import pytest

from sim.instruments import (Transmitter, counts_valid, counts_saturated, legacy_flow, LEGACY_CONSTANTS,
                             COUNTS_OPEN_CIRCUIT, COUNTS_SATURATED_LOW, COUNTS_SATURATED_HIGH,
                             FAULT_OPEN, FAULT_STUCK)


def make_tx(**kw):
    args = dict(eng_min=-500.0, eng_max=500.0, tau_s=0.001, noise_std=0.0, rng=random.Random(1))
    args.update(kw)
    return Transmitter(**args)


@pytest.mark.parametrize("true_value, counts", [(-500, 0), (0, 3000), (500, 6000), (250, 4500)])
def test_scales_to_plc_counts(true_value, counts):
    assert make_tx().sample(true_value, 1.0) == counts


def test_counts_saturate_like_a_real_4_20_ma_transmitter():
    """A healthy transmitter stays within about 3.8..20.5 mA, so far-out values pin just outside 0..6000."""
    tx = make_tx()
    assert tx.sample(5000, 1.0) == COUNTS_SATURATED_HIGH == 6188
    tx2 = make_tx()
    assert tx2.sample(-5000, 1.0) == COUNTS_SATURATED_LOW == -75
    assert counts_valid(COUNTS_SATURATED_LOW) and counts_valid(COUNTS_SATURATED_HIGH)   # not a fault code


def test_one_sided_transmitter_cannot_read_suction():
    """Site transmitters span 0..250 Pa: any suction reads as a few pascals below zero."""
    tx = make_tx(eng_min=0.0, eng_max=250.0)
    assert tx.sample(125, 1.0) == 3000
    counts = make_tx(eng_min=0.0, eng_max=250.0).sample(-60, 1.0)
    assert counts == COUNTS_SATURATED_LOW and counts_saturated(counts)
    assert not counts_saturated(3000)
    assert not counts_saturated(8000)          # the open-circuit code is a fault, not saturation


def test_negative_pressure_gives_counts_below_midscale():
    assert make_tx().sample(-100, 1.0) < 3000


def test_open_circuit_reads_8000_and_is_flagged_invalid():
    tx = make_tx()
    tx.fault = FAULT_OPEN
    counts = tx.sample(100, 1.0)
    assert counts == COUNTS_OPEN_CIRCUIT == 8000
    assert not counts_valid(counts)


def test_stuck_transmitter_holds_its_last_counts():
    tx = make_tx()
    tx.sample(100, 1.0)
    held = tx.sample(100, 1.0)
    tx.fault = FAULT_STUCK
    assert tx.sample(-400, 1.0) == held
    assert counts_valid(held)          # a stuck sensor looks healthy: the controller cannot tell


def test_offset_shifts_the_reading():
    tx = make_tx()
    tx.offset = 50.0
    assert tx.sample(0, 1.0) == 3300


def test_first_order_lag():
    tx = make_tx(tau_s=10.0)
    tx.sample(0, 1.0)                       # initialise the filter at 0
    for _ in range(10):                     # 10 s = one time constant, signal jumps to 100
        counts = tx.sample(100, 1.0)
    expected_eng = 100 * (1 - 0.36788)
    assert counts == pytest.approx(3000 + expected_eng * 6, abs=2)


def test_noise_is_repeatable_for_a_seed_and_has_the_requested_spread():
    a = make_tx(noise_std=10.0, rng=random.Random(7))
    b = make_tx(noise_std=10.0, rng=random.Random(7))
    seq_a = [a.sample(0, 1.0) for _ in range(500)]
    assert seq_a == [b.sample(0, 1.0) for _ in range(500)]
    std_counts = (sum((c - 3000) ** 2 for c in seq_a) / len(seq_a)) ** 0.5
    assert std_counts == pytest.approx(10.0 * 6, rel=0.2)       # 6 counts per Pa


@pytest.mark.parametrize("counts, valid", [(0, True), (6000, True), (-300, True), (6300, True),
                                           (-301, False), (6301, False), (8000, False)])
def test_counts_valid_band(counts, valid):
    assert counts_valid(counts) is valid


# --------------------------------------------------------------------------- legacy flow value
def test_legacy_constants_are_the_fan_ctrl_defaults():
    assert LEGACY_CONSTANTS.c == 0.7 and LEGACY_CONSTANTS.k == 1.4 and LEGACY_CONSTANTS.m == 89
    assert LEGACY_CONSTANTS.a2 == pytest.approx(0.6096 ** 2)


def test_legacy_value_at_the_site_operating_point():
    """Characterisation: calc_pv as coded, gauge pressures, T in kelvin. The old screen averaged about 40."""
    assert legacy_flow(119.2, 87.0, 130.4) == pytest.approx(31.007, abs=0.01)


@pytest.mark.parametrize("p1, p2", [(0.0, 0.0), (-5.0, -10.0), (50.0, -3.0), (50.0, 60.0)])
def test_legacy_value_is_missing_where_the_formula_cannot_be_evaluated(p1, p2):
    assert legacy_flow(p1, p2, 130.0) is None


def test_legacy_value_depends_on_pressure_level_not_only_on_the_differential():
    """Same 30 Pa across the plate, different back-pressure: the legacy value changes."""
    assert legacy_flow(60, 30, 130) > legacy_flow(230, 200, 130) * 1.3
