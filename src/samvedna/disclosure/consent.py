"""The consent registry and its lifecycle (Workflow B).

Granular, revocable, and evaluated on every run rather than cached. Four states,
and the only transition with a deadline attached is revocation: within one cycle
the self-report and biometric rows are purged, the pid leaves every open MONITOR
watchlist, and any queued-but-undelivered alert is cancelled.

**Revocation is never punished and never reported.** It is visible to the auditor
and to nobody else — not the commanding officer, not the welfare officer. There
is no "recently revoked" list, no count on a dashboard, and no field anywhere
that a report could group by. That is a design constraint, not a setting.

Consent is also recorded **against the text the person actually read**, in the
language they read it in — see `consent_text.py`. The receipt lives here rather
than on `ConsentState` because the decision layer has no business knowing what
language somebody speaks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from samvedna.config.weights import ALL_DOMAINS, DomainName
from samvedna.core.types import ConsentState
from samvedna.disclosure.consent_text import (
    ConsentReceipt,
    LocaleText,
    locale_text,
    make_receipt,
)

__all__ = ["ConsentRegistry", "PurgeResult", "CONSENT_STATES", "StaleConsent"]


class StaleConsent(RuntimeError):
    """The text this person consented to is no longer the text being shown."""

CONSENT_STATES = ("NOT_ENROLLED", "ACTIVE", "PARTIAL", "REVOKED")


@dataclass(frozen=True, slots=True)
class PurgeResult:
    """What a revocation actually removed. Returned so it can be shown to the
    person in-app — "it is done" is only credible with a number behind it."""

    pid: str
    self_report_rows: int
    biometric_rows: int
    watchlists_left: int
    alerts_cancelled: int


@dataclass
class ConsentRegistry:
    """In-memory registry. The persistent implementation is the same shape.

    Keyed by pid: this registry sits downstream of pseudonymisation, so a leak of
    the consent store is not a leak of who is enrolled.
    """

    _states: dict[str, ConsentState] = field(default_factory=dict)
    _revocation_ledger: list[tuple[str, datetime]] = field(default_factory=list)
    _receipts: dict[str, ConsentReceipt] = field(default_factory=dict)

    def state_for(self, pid: str) -> ConsentState | None:
        return self._states.get(pid)

    def enrol_with_receipt(
        self,
        pid: str,
        scope: frozenset[DomainName] | tuple[DomainName, ...],
        *,
        welfare_contact: bool,
        locale: str,
        pilot_mode: bool = False,
        locale_dir: str | None = None,
        at: datetime | None = None,
    ) -> tuple[ConsentState, ConsentReceipt]:
        """Enrol, recording exactly what text the person read.

        Raises `ConsentTextUnavailable` if the locale is unknown, or if it is a
        draft translation and this is not a pilot. Refusing is the point: the
        alternative is a consent record that cannot answer "agreed to what?".
        """
        kwargs = {"directory": locale_dir} if locale_dir else {}
        receipt = make_receipt(
            pid, locale, scope,
            welfare_contact=welfare_contact, pilot_mode=pilot_mode, at=at, **kwargs,
        )
        state = self.enrol(pid, scope, welfare_contact=welfare_contact, at=at)
        self._receipts[pid] = receipt
        return state, receipt

    def receipt_for(self, pid: str) -> ConsentReceipt | None:
        return self._receipts.get(pid)

    def needs_reconsent(
        self, pid: str, *, locale_dir: str | None = None
    ) -> tuple[bool, str]:
        """Has the text moved under this person since they agreed?

        Returns (needs_asking_again, why). A person who agreed to the September
        wording did not agree to the October wording, and carrying the old
        agreement forward is exactly what the version field exists to prevent.
        """
        receipt = self._receipts.get(pid)
        if receipt is None:
            state = self._states.get(pid)
            if state is None or state.status in ("NOT_ENROLLED", "REVOKED"):
                return False, "not enrolled"
            return True, "no receipt was recorded for this consent"
        kwargs = {"directory": locale_dir} if locale_dir else {}
        current: LocaleText = locale_text(receipt.locale, **kwargs)
        if receipt.is_current(current):
            return False, "consent matches the current text"
        return True, (
            f"the {current.english_name} consent text has changed since this person "
            f"agreed (they read {receipt.text_version}, current is "
            f"{current.text_version}); they must be asked again rather than carried over"
        )

    def enrol(
        self,
        pid: str,
        scope: frozenset[DomainName] | tuple[DomainName, ...],
        *,
        welfare_contact: bool,
        at: datetime | None = None,
    ) -> ConsentState:
        scope = frozenset(scope)
        status = "ACTIVE" if scope == frozenset(ALL_DOMAINS) else "PARTIAL"
        state = ConsentState(
            pid=pid,
            scope=scope,
            welfare_contact=welfare_contact,
            status=status if scope else "NOT_ENROLLED",
            updated_at=at or datetime.now(UTC),
        )
        self._states[pid] = state
        return state

    def narrow(self, pid: str, drop: tuple[DomainName, ...], *, at=None) -> ConsentState:
        current = self._states[pid]
        return self.enrol(
            pid,
            current.scope - frozenset(drop),
            welfare_contact=current.welfare_contact,
            at=at,
        )

    def widen(self, pid: str, add: tuple[DomainName, ...], *, at=None) -> ConsentState:
        current = self._states[pid]
        return self.enrol(
            pid,
            current.scope | frozenset(add),
            welfare_contact=current.welfare_contact,
            at=at,
        )

    def set_welfare_contact(self, pid: str, allowed: bool, *, at=None) -> ConsentState:
        current = self._states[pid]
        return self.enrol(pid, current.scope, welfare_contact=allowed, at=at)

    def revoke(self, pid: str, *, at: datetime | None = None) -> ConsentState:
        """One tap. Everything downstream must act within one cycle."""
        when = at or datetime.now(UTC)
        state = ConsentState(
            pid=pid,
            scope=frozenset(),
            welfare_contact=False,
            status="REVOKED",
            updated_at=when,
        )
        self._states[pid] = state
        # The receipt goes with the consent. Keeping it would leave a record of
        # what a withdrawn person had once agreed to, which is content the
        # purge is meant to remove.
        self._receipts.pop(pid, None)
        self._revocation_ledger.append((pid, when))
        return state

    def complete_revocation(self, pid: str, *, at=None) -> ConsentState:
        """After the purge, the person is simply not enrolled. No residue."""
        state = ConsentState(
            pid=pid,
            scope=frozenset(),
            welfare_contact=False,
            status="NOT_ENROLLED",
            updated_at=at or datetime.now(UTC),
        )
        self._states[pid] = state
        return state

    def enrolled_pids(self) -> tuple[str, ...]:
        return tuple(
            pid for pid, s in self._states.items() if s.status in ("ACTIVE", "PARTIAL")
        )

    def revocations_for_auditor(self) -> tuple[tuple[str, datetime], ...]:
        """The ONLY accessor for revocation events, and its name says who may
        call it. There is deliberately no count, no rate and no per-unit view."""
        return tuple(self._revocation_ledger)
