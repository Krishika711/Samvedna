"""L5 — the only place a pid becomes a person.

This module exists so that "where can a name come out?" has a one-word answer.
Re-identification is impossible from L2 or L3, not by convention but because
neither layer holds a directory or a salt, and because the function that does the
work refuses to run without an authorised principal, a bound purpose, and a
successful ledger write.

Read `disclose` as a sequence of refusals. Everything before the return is a
reason not to release a name, and there is no other return.

**A failed ledger write aborts the disclosure.** That is PART 8.8's last row, and
it is enforced by writing the entry *before* the identity is looked up, so there
is no ordering in which a name is produced without a record of it.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from samvedna.core.types import Verdict
from samvedna.disclosure.audit import Ledger, LedgerWriteFailed
from samvedna.disclosure.consent import ConsentRegistry
from samvedna.disclosure.rbac import Denied, Principal, check

__all__ = ["Identity", "Directory", "Disclosure", "disclose", "DisclosureRefused"]


class DisclosureRefused(PermissionError):
    """Refused, with the reason. Never a silent empty result."""


@dataclass(frozen=True, slots=True)
class Identity:
    """The minimum a welfare officer needs to find and approach a person.

    Note what is not here: no psychometric responses, no raw self-report text, no
    clinical history. A welfare officer receives an identity, the drivers in
    plain language, and a recommended action — PART 8.0 is explicit that raw
    psychometric responses are something they may never see.
    """

    service_number: str
    name: str
    rank: str
    unit_id: str
    contact: str


class Directory(Protocol):
    """Resolves a pid to a person. The only holder of that mapping.

    In production this is a service inside the unit's records boundary, reached
    with the HSM salt for the epoch the pid was minted in. A pid from an expired
    epoch must fail to resolve rather than resolve to the wrong person.
    """

    def resolve(self, pid: str) -> Identity | None: ...


@dataclass(frozen=True, slots=True)
class Disclosure:
    """A released identity, and the audit entry that permitted it."""

    identity: Identity
    pid: str
    purpose: str
    principal: str
    ledger_seq: int
    at: datetime


def disclose(
    *,
    pid: str,
    verdict: Verdict,
    principal: Principal,
    purpose: str,
    unit_id: str,
    directory: Directory,
    ledger: Ledger,
    consent: ConsentRegistry,
    justification: str = "",
    at: datetime | None = None,
) -> Disclosure:
    """Turn a pid into a person, or refuse and say why.

    The order of these checks is the design. Authorisation before consent, because
    an unauthorised request should not even reveal whether the person consented.
    Consent before the verdict, because a person who withdrew is not a case. The
    verdict before the ledger, because there is no point recording a disclosure
    that was never going to happen. And the ledger before the directory, because
    a name must not exist in this process before the record of it exists on disk.
    """
    when = at or datetime.now(UTC)

    # 1. Authorisation and purpose binding. Raises on refusal.
    may_identify = check(principal, purpose, unit_id)
    if not may_identify:
        _log_denial(ledger, principal, pid, unit_id, purpose, "aggregate-only grant", when)
        raise DisclosureRefused(
            f"{principal.actor} may act for '{purpose}' but only on aggregate data"
        )

    # 2. Consent. An acute route is the one purpose that proceeds without an
    #    explicit welfare-contact grant, because submitting the disclosure was
    #    itself the act of asking for help.
    state = consent.state_for(pid)
    if state is None or state.status in ("NOT_ENROLLED", "REVOKED"):
        _log_denial(ledger, principal, pid, unit_id, purpose, "no consent basis", when)
        raise DisclosureRefused("no consent basis for this pid")
    if purpose != "welfare:acute" and not state.welfare_contact:
        _log_denial(
            ledger, principal, pid, unit_id, purpose, "welfare contact not consented", when
        )
        raise DisclosureRefused("consent does not extend to welfare contact")

    # 3. The verdict must actually name somebody. MONITOR and NO_FLAG never do.
    if not verdict.names_a_person:
        _log_denial(
            ledger, principal, pid, unit_id, purpose,
            f"verdict is {verdict.decision}", when,
        )
        raise DisclosureRefused(
            f"a {verdict.decision} verdict does not disclose an identity"
        )

    # 4. The ledger, BEFORE the lookup. A failed write aborts the disclosure and
    #    no name is released.
    try:
        entry = ledger.append(
            actor=principal.actor,
            action="disclosure.granted",
            subject_pid=pid,
            unit_id=unit_id,
            purpose=purpose,
            detail={
                "decision": verdict.decision,
                "composite": round(verdict.composite, 4),
                "config_version": verdict.config_version,
                "override": verdict.override,
                "justification": justification,
            },
            at=when,
        )
    except LedgerWriteFailed as exc:
        raise DisclosureRefused(
            f"disclosure aborted: the audit record could not be written ({exc}). "
            f"No identity has been released."
        ) from exc

    # 5. Only now.
    identity = directory.resolve(pid)
    if identity is None:
        raise DisclosureRefused(
            f"pid could not be resolved (expired salt epoch, or unknown pid). "
            f"Ledger entry {entry.seq} records the attempt."
        )

    return Disclosure(
        identity=identity,
        pid=pid,
        purpose=purpose,
        principal=principal.actor,
        ledger_seq=entry.seq,
        at=when,
    )


def _log_denial(
    ledger: Ledger,
    principal: Principal,
    pid: str,
    unit_id: str,
    purpose: str,
    reason: str,
    at: datetime,
) -> None:
    """Denials are logged too. An auditor needs to see what was *asked*.

    A failed write here is suppressed, and that asymmetry with `disclose` is
    deliberate: failing to record a refusal must never turn the refusal into a
    grant. The caller has already raised by the time this returns.
    """
    with contextlib.suppress(LedgerWriteFailed):
        ledger.append(
            actor=principal.actor,
            action="disclosure.denied",
            subject_pid=pid,
            unit_id=unit_id,
            purpose=purpose,
            detail={"reason": reason},
            at=at,
        )


def try_disclose(**kwargs) -> tuple[Disclosure | None, str]:
    """Non-raising wrapper for API handlers. Never returns a partial identity."""
    try:
        return disclose(**kwargs), ""
    except (DisclosureRefused, Denied) as exc:
        return None, str(exc)
