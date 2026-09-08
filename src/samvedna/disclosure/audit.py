"""The append-only, hash-chained audit ledger.

Every access, score, verdict, override and consent change is written here, and
nothing is ever updated or deleted. Each entry carries the hash of the one before
it, so an entry cannot be altered or removed without breaking every hash after
it — which is what makes the ledger *tamper-evident* rather than merely
append-only-by-convention.

Two rules that are not obvious and both matter:

**A ledger entry holds the fact of an event, never its content.** The outcome
category of a welfare conversation is recorded; a word of what was said is not.
An auditor can see that a welfare officer re-identified a pid at 07:14 and what
the stated purpose was, and cannot see the person's self-report.

**A failed ledger write aborts the disclosure.** No name is released without an
audit record. This is enforced by `disclose_with_audit` writing the entry
*before* the identity is returned, and by there being no code path that returns
an identity without one.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal

__all__ = ["Entry", "Ledger", "LedgerWriteFailed", "Action", "GENESIS"]

Action = Literal[
    "run.started", "run.completed", "run.partial",
    "consent.granted", "consent.narrowed", "consent.widened", "consent.revoked",
    "consent.purged",
    "score.computed", "verdict.recorded", "override.applied",
    "disclosure.requested", "disclosure.granted", "disclosure.denied",
    "case.contacted", "case.closed", "case.deferred", "case.dismissed",
    "annotation.accepted", "annotation.rejected", "correction.requested",
    "aggregate.released", "aggregate.suppressed",
    "config.changed", "model.frozen",
]

GENESIS = "0" * 64


class LedgerWriteFailed(RuntimeError):
    """Raised when an entry could not be committed. Callers must abort."""


@dataclass(frozen=True, slots=True)
class Entry:
    seq: int
    at: datetime
    actor: str  # a role plus an operator id — never a subject's name
    action: Action
    subject_pid: str  # pseudonymous, always
    unit_id: str
    purpose: str
    detail: dict[str, str | int | float | bool]
    prev_hash: str
    entry_hash: str = ""

    def payload(self) -> str:
        body = {
            "seq": self.seq,
            "at": self.at.isoformat(),
            "actor": self.actor,
            "action": self.action,
            "subject_pid": self.subject_pid,
            "unit_id": self.unit_id,
            "purpose": self.purpose,
            "detail": self.detail,
            "prev_hash": self.prev_hash,
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":"))

    def compute_hash(self) -> str:
        return hashlib.sha256(self.payload().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        out = asdict(self)
        out["at"] = self.at.isoformat()
        return out


@dataclass
class Ledger:
    """In-memory hash chain. The persistent implementation is the same shape
    backed by an append-only table with no UPDATE or DELETE grant."""

    _entries: list[Entry] = field(default_factory=list)
    # Test/ops hook: simulate a storage failure so the abort path is exercisable.
    fail_next_write: bool = False

    @property
    def head(self) -> str:
        return self._entries[-1].entry_hash if self._entries else GENESIS

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        """A ledger is always truthy, even when empty.

        Defining `__len__` makes an empty instance falsy, and `ledger or
        Ledger()` then silently discards the caller's ledger and writes the run
        to a throwaway one. That is exactly what happened the first time this was
        wired up: the nightly run appended nine entries to a ledger nobody could
        see, and the audit trail for the run simply did not exist. An empty
        ledger is not "no ledger" — it is a ledger with nothing in it yet.
        """
        return True

    def append(
        self,
        *,
        actor: str,
        action: Action,
        subject_pid: str = "",
        unit_id: str = "",
        purpose: str = "",
        detail: dict | None = None,
        at: datetime | None = None,
    ) -> Entry:
        if self.fail_next_write:
            self.fail_next_write = False
            raise LedgerWriteFailed(f"{action}: storage rejected the append")

        entry = Entry(
            seq=len(self._entries),
            at=at or datetime.now(UTC),
            actor=actor,
            action=action,
            subject_pid=subject_pid,
            unit_id=unit_id,
            purpose=purpose,
            detail=dict(detail or {}),
            prev_hash=self.head,
        )
        sealed = Entry(
            **{**entry.to_dict(), "at": entry.at, "entry_hash": entry.compute_hash()}
        )
        self._entries.append(sealed)
        return sealed

    # Read paths. There is deliberately no update and no delete.
    def entries(self) -> tuple[Entry, ...]:
        return tuple(self._entries)

    def for_pid(self, pid: str) -> tuple[Entry, ...]:
        return tuple(e for e in self._entries if e.subject_pid == pid)

    def for_action(self, action: Action) -> tuple[Entry, ...]:
        return tuple(e for e in self._entries if e.action == action)

    def verify(self) -> tuple[bool, str]:
        """Walk the chain. Returns (ok, reason) — reason names the first break."""
        prev = GENESIS
        for index, entry in enumerate(self._entries):
            if entry.seq != index:
                return False, f"entry {index}: sequence is {entry.seq}"
            if entry.prev_hash != prev:
                return False, f"entry {index}: prev_hash does not match entry {index - 1}"
            if entry.entry_hash != entry.compute_hash():
                return False, f"entry {index}: content does not match its hash"
            prev = entry.entry_hash
        return True, "chain verified"
