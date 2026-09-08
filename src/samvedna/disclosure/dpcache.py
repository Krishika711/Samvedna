"""Released aggregates are remembered, and re-served rather than re-noised.

This is a correctness requirement, not an optimisation, and it is the one part of
the differential-privacy story that is easy to get backwards.

If a commander refreshes their unit view ten times and each refresh draws fresh
Laplace noise around the same true value, the ten answers average to the truth.
The privacy guarantee is destroyed by the refresh button. It cost 7 epsilon of a
10 epsilon budget to render one unit view during integration, and the obvious
reading — "raise the budget" — is precisely the wrong lesson: a bigger budget
buys more samples to average.

So a released cell is cached against (unit, date, label). The same question gets
the same answer for the period, and the budget is only charged the first time.
A *different* question costs epsilon, which is correct, because a different
question is a different disclosure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from samvedna.disclosure.kanon import Cell

__all__ = ["ReleaseCache"]


@dataclass
class ReleaseCache:
    """Per-period memory of what has already been released.

    Keyed by (unit_id, as_of, label) so a new run genuinely does produce new
    numbers, while a refresh within the run does not.
    """

    _cells: dict[tuple[str, str, str], Cell] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def key(self, unit_id: str, as_of: date, label: str) -> tuple[str, str, str]:
        return (unit_id, as_of.isoformat(), label)

    def get(self, unit_id: str, as_of: date, label: str) -> Cell | None:
        cell = self._cells.get(self.key(unit_id, as_of, label))
        if cell is None:
            self.misses += 1
        else:
            self.hits += 1
        return cell

    def put(self, unit_id: str, as_of: date, label: str, cell: Cell) -> Cell:
        self._cells[self.key(unit_id, as_of, label)] = cell
        return cell

    def __len__(self) -> int:
        return len(self._cells)

    def __bool__(self) -> bool:
        # An empty cache is still a cache. See `Ledger.__bool__` for why this
        # matters more than it looks.
        return True
