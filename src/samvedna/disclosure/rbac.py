"""Roles, purposes, and the binding between them.

RBAC alone is not enough for this system. A welfare officer and an ACR clerk can
both be "authenticated staff of the same unit"; what separates them is *why* they
are asking. So every grant is a (role, purpose) pair, and a purpose outside the
welfare set is refused regardless of role — that is the purpose firewall in
PART 10, expressed as a lookup table rather than as a policy document.

The table below is the whole authorisation model, and it is deliberately short
enough to read in one sitting and argue with.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "Role",
    "Purpose",
    "Principal",
    "GRANTS",
    "FORBIDDEN_PURPOSES",
    "may",
    "Denied",
    "check",
]

Role = Literal[
    "personnel", "welfare_officer", "commander", "mental_health_authority", "auditor"
]

Purpose = Literal[
    "welfare:screening",
    "welfare:contact",
    "welfare:acute",
    "welfare:self",
    "command:aggregate",
    "governance:audit",
    # Everything below is refused for every role, always. They are listed rather
    # than omitted so the refusal is visible in the code and in the tests, and so
    # that adding one by accident is a diff somebody has to defend.
    "administrative:acr",
    "administrative:promotion",
    "administrative:posting",
    "administrative:disciplinary",
]

FORBIDDEN_PURPOSES: frozenset[str] = frozenset(
    {
        "administrative:acr",
        "administrative:promotion",
        "administrative:posting",
        "administrative:disciplinary",
    }
)

# (role, purpose) -> may this principal see an identity?
# `False` means the role may act for that purpose but only on aggregate or
# pseudonymous data. Absent means refused outright.
# Roles whose authority is bounded by unit, and which therefore may not hold an
# empty scope.
#
# The scope check used to read `if unit_id and principal.unit_scope and ...`,
# which skips the comparison entirely when the scope is empty — so a welfare
# officer who declared no units could read every unit in the force. That is
# fail-open on the one axis that decides who may see a name. It was found by
# noticing that a caseload request with `X-Units:` empty returned four cases
# while the same request naming two units returned two.
#
# An auditor is deliberately absent: the ledger is force-wide by design, and the
# grant table already forbids an auditor from re-identifying anybody. Personnel
# are absent because their authority is over themselves, not a unit.
UNIT_SCOPED_ROLES: frozenset[str] = frozenset({"welfare_officer", "commander"})

GRANTS: dict[tuple[str, str], bool] = {
    ("welfare_officer", "welfare:screening"): False,
    ("welfare_officer", "welfare:contact"): True,
    # The acute path's owner. `welfare:acute` is the only purpose under which
    # an acute case's identity resolves, and no other role holds it — PHQ-9
    # item 9 is a clinical disclosure and it routes to a clinician.
    #
    # `welfare:screening` was missing, which left the role unable to *see* the
    # cases it alone is allowed to act on. An end-to-end walk found it: the case
    # appeared on the welfare officer's caseload with an urgent recommendation
    # and a disclose button that returned "role 'welfare_officer' has no grant
    # for purpose 'welfare:acute'". The routing was right and there was nobody
    # on the other end of it.
    ("mental_health_authority", "welfare:screening"): False,
    ("mental_health_authority", "welfare:acute"): True,
    ("commander", "command:aggregate"): False,
    ("personnel", "welfare:self"): True,
    ("auditor", "governance:audit"): False,
}


class Denied(PermissionError):
    """Raised instead of returning a falsy value, so it cannot be ignored."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is asking, in what role, for what, and over which unit.

    `unit_scope` is empty for an auditor (the ledger is force-wide) and holds the
    units a welfare officer or commander is responsible for. An officer asking
    about another unit is refused even for a permitted purpose.
    """

    subject_id: str  # an operator id, never a subject's identity
    role: Role
    unit_scope: frozenset[str] = frozenset()

    @property
    def actor(self) -> str:
        """How this principal appears in the audit ledger."""
        return f"{self.role}:{self.subject_id}"


def may(role: str, purpose: str) -> bool | None:
    """True = may re-identify. False = permitted, aggregate only. None = refused."""
    if purpose in FORBIDDEN_PURPOSES:
        return None
    return GRANTS.get((role, purpose))


def check(principal: Principal, purpose: str, unit_id: str = "") -> bool:
    """Authorise, or raise. Returns whether re-identification is permitted.

    Raising rather than returning False is deliberate: a caller that forgets to
    check a boolean gets a name; a caller that forgets to catch an exception gets
    a stack trace. Only one of those failure modes is safe.
    """
    if purpose in FORBIDDEN_PURPOSES:
        raise Denied(
            f"purpose '{purpose}' is barred for every role. Outputs of this system "
            f"are not available to ACR, promotion, posting or disciplinary processes."
        )
    grant = GRANTS.get((principal.role, purpose))
    if grant is None:
        raise Denied(f"role '{principal.role}' has no grant for purpose '{purpose}'")
    if principal.role in UNIT_SCOPED_ROLES and not principal.unit_scope:
        raise Denied(
            f"{principal.actor} has no unit scope. A {principal.role} acts for "
            f"named units; an empty scope is no authority, not universal "
            f"authority."
        )
    if unit_id and principal.unit_scope and unit_id not in principal.unit_scope:
        raise Denied(
            f"{principal.actor} is not responsible for {unit_id}; "
            f"scope is {sorted(principal.unit_scope)}"
        )
    return grant
