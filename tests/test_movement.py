"""Unit tests for MovementEstimator, the cover's pure position state machine.

These exercise the exact class EzvizHg2Cover delegates to (see
custom_components/ezviz_hg2/cover.py), not a reimplementation, so they cover
the "Position" scenarios from the refactor brief without needing Home
Assistant importable: a gate found open at startup must not be assumed to
be at 100%, a movement estimate only starts when told to (i.e. after a
command succeeds), and it resolves to the target once its duration elapses.
"""

from __future__ import annotations

import pytest

from _load import load

travel = load("travel")
MovementEstimator = travel.MovementEstimator


def test_fresh_estimator_has_no_position():
    # A gate observed "open" at Home Assistant startup must not be assumed
    # to be at 100%: nothing has told the estimator to start a movement, so
    # position stays unknown.
    estimator = MovementEstimator()
    assert estimator.position_at(now=1000.0) is None
    assert estimator.is_moving is False


def test_start_does_nothing_without_a_calibrated_duration():
    estimator = MovementEstimator()
    estimator.start(100.0, None, now=0.0)
    assert estimator.is_moving is False
    assert estimator.position_at(now=0.0) is None


def test_start_from_unknown_position_assumes_the_opposite_extreme():
    estimator = MovementEstimator()
    estimator.start(100.0, 10.0, now=0.0)
    assert estimator.position_at(now=0.0) == 0.0

    estimator2 = MovementEstimator()
    estimator2.start(0.0, 10.0, now=0.0)
    assert estimator2.position_at(now=0.0) == 100.0


def test_position_progresses_and_completes_at_the_target():
    estimator = MovementEstimator()
    estimator.start(100.0, 10.0, now=0.0)
    mid = estimator.position_at(now=5.0)
    assert mid is not None
    assert 0.0 < mid < 100.0

    finished = estimator.position_at(now=10.0)
    assert finished == 100.0
    assert estimator.is_moving is False


def test_position_at_or_past_full_duration_snaps_and_clears():
    estimator = MovementEstimator()
    estimator.start(0.0, 5.0, now=0.0)
    assert estimator.position_at(now=999.0) == 0.0
    assert estimator.is_moving is False


def test_is_moving_and_target_reflect_the_current_direction():
    estimator = MovementEstimator()
    assert estimator.target is None
    estimator.start(100.0, 10.0, now=0.0)
    assert estimator.is_moving is True
    assert estimator.target == 100.0


def test_clear_freezes_the_last_known_position():
    estimator = MovementEstimator()
    estimator.start(100.0, 10.0, now=0.0)
    estimator.position = estimator.position_at(now=5.0)
    estimator.clear()
    assert estimator.is_moving is False
    frozen = estimator.position
    assert estimator.position_at(now=999.0) == frozen


def test_restarting_mid_move_continues_from_the_interpolated_position():
    estimator = MovementEstimator()
    estimator.start(100.0, 10.0, now=0.0)
    midpoint = estimator.position_at(now=5.0)
    estimator.start(0.0, 10.0, now=5.0)
    assert estimator.position_at(now=5.0) == pytest.approx(midpoint, abs=1e-6)
    assert estimator.target == 0.0


def test_explicit_closed_position_does_not_require_a_movement():
    # Mirrors _handle_coordinator_update: DoorStatus == 0 sets position
    # directly without ever calling start().
    estimator = MovementEstimator()
    estimator.position = 0.0
    assert estimator.position_at(now=0.0) == 0.0
    assert estimator.is_moving is False
