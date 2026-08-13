"""Pure travel-position easing math for the HG2 gate cover.

Kept free of Home Assistant imports so the curve used to estimate an
in-progress gate position can be unit tested without booting Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def eased_fraction(fraction: float) -> float:
    """Smoothstep 0..1: slow at both ends, matching the gate motor's ramp."""
    fraction = min(1.0, max(0.0, fraction))
    return fraction * fraction * (3 - 2 * fraction)


def inverse_eased_fraction(target_fraction: float) -> float:
    """Invert the smoothstep easing via Newton's method."""
    target_fraction = min(1.0, max(0.0, target_fraction))
    guess = target_fraction
    for _ in range(20):
        value = guess * guess * (3 - 2 * guess) - target_fraction
        slope = 6 * guess * (1 - guess)
        if abs(slope) < 1e-9:
            break
        guess = min(1.0, max(0.0, guess - value / slope))
    return guess


@dataclass
class MovementEstimator:
    """Pure state machine for the HG2's simulated travel position.

    EZVIZ only ever reports closed vs. not-closed, so this estimates the
    position of an in-progress move from a calibrated travel duration and
    the smoothstep easing curve above. It is deliberately free of Home
    Assistant and wall-clock (``monotonic()``) dependencies: callers pass
    the current time explicitly, which makes the whole state machine
    directly unit testable. ``EzvizHg2Cover`` owns one instance and only
    calls :meth:`start` once a command's outcome is known, so a failed
    command never leaves it mid-"move".

    ``position`` starts at ``None`` and stays there until either a
    movement is started or it is set explicitly (e.g. once EZVIZ confirms
    the gate is fully closed). This avoids inventing a 100% position for a
    gate that was already open, partially or fully, before Home Assistant
    started.
    """

    position: float | None = None
    _start_time: float | None = field(default=None, repr=False)
    _start_position: float | None = field(default=None, repr=False)
    _target: float | None = field(default=None, repr=False)
    _duration: float | None = field(default=None, repr=False)

    @property
    def is_moving(self) -> bool:
        """Return whether a simulated movement is currently in progress."""
        return self._start_time is not None

    @property
    def target(self) -> float | None:
        """Return the position a movement in progress is heading toward."""
        return self._target

    def start(self, target: float, duration: float | None, *, now: float) -> None:
        """Begin (or redirect) a simulated move toward ``target``.

        No-op when ``duration`` is unknown (travel time not calibrated).
        """
        if duration is None:
            return
        current = self.position_at(now)
        if current is None:
            current = 0.0 if target == 100.0 else 100.0
        self.position = current
        self._start_time = now
        self._start_position = current
        self._target = target
        self._duration = duration

    def clear(self) -> None:
        """Stop simulating movement, keeping the last known position."""
        self._start_time = None
        self._start_position = None
        self._target = None
        self._duration = None

    def position_at(self, now: float) -> float | None:
        """Return the estimated position at ``now``.

        Resolves (and clears) a movement whose full duration has elapsed,
        snapping ``position`` to the target.
        """
        if self._start_time is None or not self._duration:
            return self.position
        elapsed = now - self._start_time
        fraction = eased_fraction(elapsed / self._duration)
        if fraction >= 1.0:
            self.position = self._target
            self.clear()
            return self.position
        assert self._start_position is not None and self._target is not None
        return self._start_position + fraction * (self._target - self._start_position)
