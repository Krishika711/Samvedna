"""Workflow B — the consent state machine, and the promise attached to revocation."""
from __future__ import annotations

from datetime import UTC, datetime

from samvedna.config.weights import ALL_DOMAINS
from samvedna.disclosure.consent import ConsentRegistry

NOW = datetime(2026, 9, 5, tzinfo=UTC)


def registry_with_one():
    r = ConsentRegistry()
    r.enrol("pid-1", ALL_DOMAINS, welfare_contact=True, at=NOW)
    return r


def test_full_scope_is_active_and_partial_scope_is_partial():
    r = registry_with_one()
    assert r.state_for("pid-1").status == "ACTIVE"
    r.narrow("pid-1", ("self_report", "biometric"), at=NOW)
    assert r.state_for("pid-1").status == "PARTIAL"


def test_widening_returns_to_active():
    r = registry_with_one()
    r.narrow("pid-1", ("biometric",), at=NOW)
    r.widen("pid-1", ("biometric",), at=NOW)
    assert r.state_for("pid-1").status == "ACTIVE"


def test_the_welfare_contact_toggle_is_independent_of_analysis_scope():
    """A person may consent to analysis but not to being approached. Without the
    toggle, actionability is 0 and the verdict is NO_FLAG — analysed, never
    surfaced. That is the correct behaviour and the consent screen says so."""
    r = registry_with_one()
    r.set_welfare_contact("pid-1", False, at=NOW)
    state = r.state_for("pid-1")
    assert state.status == "ACTIVE"
    assert state.scope == frozenset(ALL_DOMAINS)
    assert not state.welfare_contact


def test_revocation_empties_the_scope_and_clears_welfare_contact():
    r = registry_with_one()
    state = r.revoke("pid-1", at=NOW)
    assert state.status == "REVOKED"
    assert state.scope == frozenset()
    assert not state.welfare_contact
    assert not any(state.covers(d) for d in ALL_DOMAINS)


def test_a_revoked_pid_leaves_the_enrolled_set_immediately():
    r = registry_with_one()
    assert "pid-1" in r.enrolled_pids()
    r.revoke("pid-1", at=NOW)
    assert "pid-1" not in r.enrolled_pids()


def test_after_the_purge_the_person_is_simply_not_enrolled():
    r = registry_with_one()
    r.revoke("pid-1", at=NOW)
    r.complete_revocation("pid-1", at=NOW)
    assert r.state_for("pid-1").status == "NOT_ENROLLED"


def test_revocation_is_visible_to_the_auditor_and_to_nobody_else():
    """PART 14 forbids surfacing the fact that a person revoked consent. The
    enforcement is that there is exactly one accessor and its name says who may
    call it — no count, no rate, no per-unit view exists to be read."""
    r = registry_with_one()
    r.revoke("pid-1", at=NOW)

    assert r.revocations_for_auditor() == (("pid-1", NOW),)

    surface = {
        name for name in dir(r)
        if not name.startswith("_") and "revocation" in name.lower()
    }
    # `complete_revocation` is a mutator that returns a ConsentState, not history.
    assert isinstance(r.complete_revocation("pid-1", at=NOW), type(r.state_for("pid-1")))
    assert surface == {"revocations_for_auditor", "complete_revocation"}, (
        f"another accessor could surface revocations: {sorted(surface)}"
    )
    # And no aggregate view exists that a commander's dashboard could group by.
    assert not hasattr(r, "revocation_count")
    assert not hasattr(r, "revocations_by_unit")
