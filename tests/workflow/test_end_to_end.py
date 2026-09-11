"""The whole system, personnel to auditor, in one pass.

Every other test in this suite checks one surface. This one walks the chain the
way a person does — a jawan sets consent, takes an assessment, an officer or a
clinician works the case, a commander reads their unit, an auditor verifies the
record — because every bug this file was written for lived *between* two
surfaces that each worked correctly on their own:

* The console's role scopes were literals: `UNIT-01,UNIT-02`. Units were later
  renamed to carry a service abbreviation (`CRPF-01`), and the welfare officer's
  caseload went quietly empty. Nothing errored. The API was asked about units
  that did not exist and correctly answered "nothing there", which is
  indistinguishable from a quiet night.
* An empty unit scope authorised **every** unit rather than none, so the fix for
  the above nearly became "send no scope at all".
* An acute referral routed to `mental_health_authority`, a role with no console,
  no actor and no caseload — so the case surfaced on the welfare officer's
  screen with an urgent recommendation and a disclose button that returned
  "no grant for purpose 'welfare:acute'".

Each of those is invisible to a per-surface test and obvious in a walk.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from samvedna.api.app import create_app
from samvedna.api.bootstrap import build_state

SEVERE_NOT_ACUTE = [3, 3, 3, 2, 2, 3, 2, 3, 0]
MILD_BUT_ACUTE = [1, 1, 2, 1, 2, 1, 1, 2, 1]
ALL_DOMAINS = [
    "leave", "deployment", "duty_roster", "transfer",
    "training", "workload", "self_report", "biometric", "voice",
]


@pytest.fixture
def world():
    state, _ = build_state(units=4, strength=60, seed=26186)
    return TestClient(create_app(state)), state


def headers(role: str, operator: str, units: str = "") -> dict:
    return {"X-Role": role, "X-Operator": operator, "X-Units": units}


def officer_scope(client: TestClient) -> str:
    """Exactly what the console derives: the run's own units.

    Read from the public `/api/run` rather than written down here, which is the
    whole point — a literal is what drifted.
    """
    units = client.get("/api/run").json()["units"]
    assert units, "the run reports no units, so no scope can be derived"
    return ",".join(units[:2])


# --------------------------------------------------------------- the walk --

def test_the_console_can_derive_every_scope_it_needs(world):
    """No screen should have to hardcode a unit name."""
    client, _ = world
    run = client.get("/api/run").json()

    assert run["units"], "/api/run must report its units"
    assert all(u.startswith("CRPF-") for u in run["units"]), run["units"]
    # And the service profile supplies the words for those echelons.
    svc = client.get("/api/service").json()
    assert svc["abbr"] == "CRPF"
    assert svc["unit"] == "Battalion"


def test_acute_walk_personnel_to_auditor(world):
    """A jawan discloses acute risk. Follow it all the way to the ledger."""
    client, state = world
    scope = officer_scope(client)
    person = headers("personnel", "SELF")
    officer = headers("welfare_officer", "WO-12", scope)
    clinician = headers("mental_health_authority", "MHA-1")
    commander = headers("commander", "CO-01", scope.split(",")[0])
    auditor = headers("auditor", "AU-03")

    # 1. The console resolves who it is acting as.
    me = client.get("/api/me/whoami", headers=person).json()
    pid = me["pid"]
    assert me["decision"] == "MONITOR", "the walk needs somebody not already named"

    officer_before = len(client.get("/api/caseload", headers=officer).json()["cases"])

    # 2. The person sets their consent, and it reaches the server.
    saved = client.post("/api/consent", headers=person, json={
        "pid": pid, "locale": "en", "scope": ALL_DOMAINS, "welfare_contact": True,
    })
    assert saved.status_code == 200
    assert "self_report" in saved.json()["domains"]

    # 3. They complete the questionnaire, disclosing acute risk.
    submitted = client.post(
        f"/api/me/{pid}/assessment", headers=person, json={"items": MILD_BUT_ACUTE}
    ).json()
    assert submitted["acute"] is True
    assert submitted["decision"] == "IMMEDIATE_ESCALATE"
    assert submitted["acute_route"]["routed_to"] == "mental_health_authority"

    # 4. It reaches the welfare officer's queue.
    cases = client.get("/api/caseload", headers=officer).json()["cases"]
    assert len(cases) == officer_before + 1
    case = next(c for c in cases if c["pid"] == pid)
    assert case["override"] is True
    assert case["recommended"][0]["authority"] == "mental_health"

    # 5. ...and the officer may NOT resolve the identity. Only one purpose
    #    permits an acute disclosure, and they do not hold it.
    refused = client.post(f"/api/case/{pid}/disclose", headers=officer)
    assert refused.status_code == 403
    assert "welfare:acute" in refused.json()["detail"]

    # 6. The clinician sees it, force-wide, and only the acute referrals.
    acute_queue = client.get("/api/caseload", headers=clinician).json()["cases"]
    assert acute_queue, "the acute role has no caseload"
    assert all(c["override"] for c in acute_queue), (
        "the clinician was shown ordinary escalations, which are not theirs"
    )
    assert pid in {c["pid"] for c in acute_queue}

    # 7. They resolve it, act, and close it out.
    named = client.post(f"/api/case/{pid}/disclose", headers=clinician)
    assert named.status_code == 200
    assert named.json()["identity"]["name"]

    assert client.post(f"/api/case/{pid}/contact", headers=clinician).status_code == 200
    closed = client.post(
        f"/api/case/{pid}/close", headers=clinician, json={"outcome": "supported"}
    )
    assert closed.status_code == 200

    # 8. The commander sees strain, and never this person.
    heat = client.get(f"/api/unit/{scope.split(',')[0]}/heatmap", headers=commander)
    assert heat.status_code == 200
    body = heat.json()
    for withheld in ("self_report", "biometric", "voice"):
        assert withheld not in body["domains"], (
            f"{withheld} reached a commander"
        )
    assert pid not in heat.text, "a pid appeared in an aggregate view"

    # 9. The auditor can verify every step, and the chain holds.
    audit = client.get("/api/audit", headers=auditor).json()
    assert audit["verified"] is True
    actions = [e["action"] for e in audit["entries"]]
    for required in (
        "consent.granted",
        "assessment.submitted",
        "override.applied",
        "disclosure.granted",
        "case.contacted",
        "case.closed",
    ):
        assert required in actions, f"{required} was never recorded"

    # 10. And the refusals are the auditor's to review, not the officer's.
    assert client.get("/api/refused", headers=auditor).status_code == 200
    assert client.get("/api/refused", headers=officer).status_code == 403


def test_non_acute_walk_stops_where_it_should(world):
    """The same walk with a severe but non-acute score names nobody."""
    client, _ = world
    scope = officer_scope(client)
    person = headers("personnel", "SELF")
    officer = headers("welfare_officer", "WO-12", scope)

    pid = client.get("/api/me/whoami", headers=person).json()["pid"]
    before = len(client.get("/api/caseload", headers=officer).json()["cases"])
    client.post("/api/consent", headers=person, json={
        "pid": pid, "locale": "en", "scope": ALL_DOMAINS, "welfare_contact": True,
    })

    body = client.post(
        f"/api/me/{pid}/assessment", headers=person, json={"items": SEVERE_NOT_ACUTE}
    ).json()

    assert body["total"] == 21
    assert body["acute"] is False
    assert body["named_to_an_officer"] is False
    assert body["mind_change"], "refused without saying what would change it"
    assert len(client.get("/api/caseload", headers=officer).json()["cases"]) == before


def test_no_role_can_reach_what_it_should_not(world):
    """Every boundary in the walk, asserted together."""
    client, _ = world
    scope = officer_scope(client)
    first_unit, second_unit = scope.split(",")[0], scope.split(",")[1]

    officer = headers("welfare_officer", "WO-12", first_unit)
    commander = headers("commander", "CO-01", first_unit)
    clinician = headers("mental_health_authority", "MHA-1")
    auditor = headers("auditor", "AU-03")
    person = headers("personnel", "SELF")

    # Unit scoping, both roles that have it.
    assert client.get(
        f"/api/unit/{second_unit}/heatmap", headers=commander
    ).status_code == 403
    # An officer scoped to one unit sees no case from the other.
    cases = client.get("/api/caseload", headers=officer).json()["cases"]
    assert all(c["unit_id"] == first_unit for c in cases)

    # Empty scope is no authority, not universal authority.
    assert client.get(
        "/api/caseload", headers=headers("welfare_officer", "WO-12")
    ).status_code == 403
    assert client.get(
        f"/api/unit/{first_unit}/heatmap", headers=headers("commander", "CO-01")
    ).status_code == 403

    # ...but the two force-wide roles keep working with none.
    assert client.get("/api/audit", headers=auditor).status_code == 200
    assert client.get("/api/caseload", headers=clinician).status_code == 200

    # Role boundaries.
    assert client.get("/api/caseload", headers=commander).status_code == 403
    assert client.get("/api/refused", headers=commander).status_code == 403
    assert client.get("/api/caseload", headers=person).status_code == 403
    assert client.get("/api/audit", headers=officer).status_code == 403
    # And no role at all is 401, not 403.
    assert client.get("/api/caseload").status_code == 401
