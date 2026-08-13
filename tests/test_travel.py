"""Unit tests for the pure travel easing math used by the gate cover."""

from __future__ import annotations

import pytest

from _load import load

travel = load("travel")


def test_eased_fraction_endpoints():
    assert travel.eased_fraction(0.0) == 0.0
    assert travel.eased_fraction(1.0) == 1.0


def test_eased_fraction_clamps_out_of_range_input():
    assert travel.eased_fraction(-1.0) == 0.0
    assert travel.eased_fraction(2.0) == 1.0


def test_eased_fraction_is_slower_at_the_ends_than_linear():
    # Smoothstep: below the midpoint it trails linear, matching a motor
    # ramp-up; the two curves only agree at 0, 0.5, and 1.
    assert travel.eased_fraction(0.25) < 0.25
    assert travel.eased_fraction(0.75) > 0.75
    assert travel.eased_fraction(0.5) == 0.5


def test_inverse_eased_fraction_round_trips():
    for target in (0.0, 0.1, 0.33, 0.5, 0.72, 0.99, 1.0):
        fraction = travel.inverse_eased_fraction(target)
        assert travel.eased_fraction(fraction) == pytest.approx(target, abs=1e-6)


def test_inverse_eased_fraction_clamps_out_of_range_input():
    assert travel.inverse_eased_fraction(-1.0) == 0.0
    assert travel.inverse_eased_fraction(2.0) == 1.0
