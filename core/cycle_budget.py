"""Deadline-aware budgeting for synchronous ASTRA deliberative cycles."""

from __future__ import annotations

import math
import time
from typing import Callable, Optional


class CycleBudget:
    """Clamp every phase so ASTRA can return before its outer process is killed.

    ``total_seconds=None`` means that the cycle is running as a persistent
    background job and therefore has no synchronous wall.  Individual model and
    oracle timeouts still apply in that mode.
    """

    def __init__(
        self,
        total_seconds: Optional[float],
        *,
        return_buffer_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self.started = clock()
        try:
            total = float(total_seconds) if total_seconds else 0.0
        except (TypeError, ValueError):
            total = 0.0
        self.total_seconds = total if total > 0 else None
        self.return_buffer_seconds = max(10.0, float(return_buffer_seconds))

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self.started)

    @property
    def remaining_seconds(self) -> Optional[float]:
        if self.total_seconds is None:
            return None
        return max(0.0, self.total_seconds - self.elapsed_seconds)

    @property
    def usable_seconds(self) -> Optional[float]:
        remaining = self.remaining_seconds
        if remaining is None:
            return None
        return max(0.0, remaining - self.return_buffer_seconds)

    def phase_timeout(
        self,
        requested_seconds: Optional[float],
        *,
        default_seconds: int = 240,
        minimum_seconds: int = 1,
        share: Optional[float] = None,
        reserve_seconds: float = 0.0,
    ) -> int:
        """Return a timeout that cannot consume the final response buffer.

        ``reserve_seconds`` holds budget back for the phases that still have to
        run AFTER this one, so a review/repair round is not started when what
        remains cannot also fund the tail (execute/analyze/navigate) or a
        follow-up repair.  ``share`` optionally caps the call at that fraction
        of the remaining usable budget.  Both default to no-op, so omitting
        them reproduces the historical clamp exactly.
        """
        try:
            requested = int(requested_seconds or default_seconds)
        except (TypeError, ValueError):
            requested = int(default_seconds)
        requested = max(int(minimum_seconds), requested)
        usable = self.usable_seconds
        if usable is None:
            return requested
        try:
            reserve = max(0.0, float(reserve_seconds or 0.0))
        except (TypeError, ValueError):
            reserve = 0.0
        allowed = max(float(minimum_seconds), float(usable) - reserve)
        if share is not None:
            try:
                fraction = float(share)
            except (TypeError, ValueError):
                fraction = 1.0
            if 0.0 < fraction < 1.0:
                allowed = min(allowed, usable * fraction)
        return max(int(minimum_seconds), min(requested, int(math.floor(allowed))))

    def can_start(self, minimum_seconds: float = 5.0) -> bool:
        usable = self.usable_seconds
        return usable is None or usable >= float(minimum_seconds)

    def snapshot(self) -> dict:
        return {
            "mode": "persistent" if self.total_seconds is None else "synchronous",
            "total_seconds": self.total_seconds,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "remaining_seconds": (
                None
                if self.remaining_seconds is None
                else round(self.remaining_seconds, 2)
            ),
            "return_buffer_seconds": self.return_buffer_seconds,
        }
