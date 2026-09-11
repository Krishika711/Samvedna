"""Submitting a self-assessment, and what must and must not follow from it.

The wellness questionnaire used to compute a score in the browser and send it
nowhere. A jawan could complete PHQ-9, see a severity band, and nothing
happened at all — no record, no re-decision, no case. Self-report is the only
T1 domain in the system and it was inert.

These tests pin the two halves of the answer, because they pull in opposite
directions and both are load-bearing:

* An **acute disclosure acts immediately.** PHQ-9 item 9 bypasses every gate
  and routes to a mental-health authority, whatever the total.
* A **severe but non-acute score does not manufacture a case.** One domain
  alone can never clear the evidence gate, and a single day's questionnaire has
  no 30- or 90-day history to satisfy persistence. Getting this wrong would
  turn the questionnaire into a self-service escalation button.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from samvedna.api.app import create_app
from samvedna.api.bootstrap import build_state

PERSON = {"X-Role": "personnel", "X-Operator": "SELF", "X-Units": ""}
OFFICER = {
    "X-Role": "welfare_officer",
    "X-Operator": "WO-12",
    "X-Units": "CRPF-01,CRPF-02",
}

# Nine PHQ-9 item scores. Item 9 is the last and is the acute-risk item.
SEVERE_NOT_ACUTE = [3, 3, 3, 2, 2, 3, 2, 3, 0]   # total 21
MILD_BUT_ACUTE = [1, 1, 2, 1, 2, 1, 1, 2, 1]     # total 12, item 9 fired
MINIMAL = [0, 0, 0, 0, 0, 0, 0, 0, 0]


@pytest.fixture
def client():
    state, _ = build_state(units=4, strength=60, seed=26186)
    return TestClient(create_app(state))


#: The officer's units. A case outside these is correctly invisible to them,
#: which is why the helper below filters on it — the first version did not, and
#: the acute test failed because the case it created landed in CRPF-03. That
#: was unit scoping working, not a bug, and it is worth a test of its own.
OFFICER_UNITS = frozenset({"CRPF-01", "CRPF-02"})


def monitor_pid(
    client: TestClient,
    *,
    in_officer_scope: bool = True,
    self_report_consent: bool | None = None,
) -> str:
    """A pid the run put under MONITOR — somebody with a real baseline.

    `self_report_consent` selects on whether bootstrap already enrolled them in
    the self-report domain. It only enrols a domain a person actually has
    records in, so 31 of the 125 MONITOR cases have never submitted a
    questionnaire and are not consented to the domain. Those are the people for
    whom the console's save button has to work, and the ones a screenshot
    caught it failing for.
    """
    state = client.app.state.samvedna
    for case in state.run.cases:
        if case.decision != "MONITOR" or case.ctx is None:
            continue
        if (case.unit_id in OFFICER_UNITS) is not in_officer_scope:
            continue
        if self_report_consent is not None:
            scope = getattr(state.consent.state_for(case.pid), "scope", ())
            if ("self_report" in scope) is not self_report_consent:
                continue
        return case.pid
    raise AssertionError("no suitable MONITOR case in the fixture run")


def consent(client: TestClient, pid: str, *, self_report: bool = True) -> None:
    scope = ["leave", "workload", "duty_roster"]
    if self_report:
        scope.append("self_report")
    client.post("/api/consent", headers=PERSON, json={
        "pid": pid, "locale": "en", "scope": scope, "welfare_contact": True,
    })


def caseload(client: TestClient) -> list[dict]:
    return client.get("/api/caseload", headers=OFFICER).json()["cases"]


# ------------------------------------------------------- the acute half --

def test_an_acute_item_reaches_an_officer_immediately(client):
    """The whole point. It must not wait for tonight's run."""
    pid = monitor_pid(client)
    consent(client, pid)
    before = len(caseload(client))

    body = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": MILD_BUT_ACUTE}
    ).json()

    assert body["acute"] is True
    assert body["decision_before"] == "MONITOR"
    assert body["decision"] == "IMMEDIATE_ESCALATE"
    assert body["named_to_an_officer"] is True

    after = caseload(client)
    assert len(after) == before + 1, "the acute case never reached the officer"
    case = next(c for c in after if c["pid"] == pid)
    assert case["override"] is True
    assert case["recommended"][0]["authority"] == "mental_health"


def test_the_acute_route_does_not_depend_on_a_high_total(client):
    """Item 9 fires on its own. A total of 12 is not severe by band."""
    pid = monitor_pid(client)
    consent(client, pid)

    body = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": MILD_BUT_ACUTE}
    ).json()

    assert body["total"] == 12
    assert body["total"] < 15, "this test needs a modest total to mean anything"
    assert body["acute"] is True
    route = body["acute_route"]
    assert route["routed_to"] == "mental_health_authority"
    assert route["acknowledge_by"], "an SLA with no deadline is not an SLA"
    assert route["resources"], "somebody at risk was offered nowhere to go"


def test_the_person_is_shown_support_not_a_score(client):
    pid = monitor_pid(client)
    consent(client, pid)
    route = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": MILD_BUT_ACUTE}
    ).json()["acute_route"]

    assert "taken seriously" in route["message"]
    assert all({"who", "how"} <= set(r) for r in route["resources"])


# --------------------------------------------- the deliberately-quiet half --

def test_a_severe_score_alone_does_not_produce_a_case(client):
    """A questionnaire is not a self-service escalation button.

    Total 21 of 27 is severe, and it still must not name anybody on its own:
    one domain cannot clear the evidence gate, and one day cannot satisfy
    persistence. The response has to say so, because a person who fills in a
    form and sees nothing happen is owed an explanation rather than silence.
    """
    pid = monitor_pid(client)
    consent(client, pid)
    before = len(caseload(client))

    body = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": SEVERE_NOT_ACUTE}
    ).json()

    assert body["total"] == 21
    assert body["acute"] is False
    assert body["named_to_an_officer"] is False
    assert len(caseload(client)) == before, "a single questionnaire named somebody"

    failed = [g["name"] for g in body["gates"] if not g["passed"]]
    assert failed, "nothing failed, yet nobody was named — that is incoherent"
    assert body["mind_change"], "refused without saying what would change it"


def test_submitting_twice_does_not_stack_into_an_escalation(client):
    """Two responses in one domain must not corroborate each other.

    The evidence gate counts distinct deviating domains. If a resubmission
    appended a second `self_report` deviation instead of replacing the first,
    a person could clear the gate with a refresh button.
    """
    pid = monitor_pid(client)
    consent(client, pid)

    first = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": SEVERE_NOT_ACUTE}
    ).json()
    second = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": SEVERE_NOT_ACUTE}
    ).json()

    assert second["named_to_an_officer"] is False
    for a, b in zip(first["gates"], second["gates"], strict=True):
        assert a["value"] == pytest.approx(b["value"]), (
            f"{a['name']} moved on a repeat submission: {a['value']} -> {b['value']}"
        )


# ------------------------------------------------------------ the guards --

def test_it_needs_consent_to_the_self_report_domain(client):
    pid = monitor_pid(client)
    consent(client, pid, self_report=False)

    r = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": SEVERE_NOT_ACUTE}
    )
    assert r.status_code == 403
    assert "self-report domain" in r.json()["detail"]


def test_only_personnel_may_submit(client):
    pid = monitor_pid(client)
    consent(client, pid)
    r = client.post(
        f"/api/me/{pid}/assessment", headers=OFFICER, json={"items": SEVERE_NOT_ACUTE}
    )
    assert r.status_code == 403


@pytest.mark.parametrize("items", [
    [3] * 8,             # too few
    [3] * 10,            # too many
    [0, 0, 0, 0, 0, 0, 0, 0, 4],   # out of range
    [0, 0, 0, 0, 0, 0, 0, 0, -1],  # negative
    ["a"] * 9,           # not numbers
])
def test_a_malformed_response_is_refused(client, items):
    """The browser's arithmetic is never trusted for a clinical instrument."""
    pid = monitor_pid(client)
    consent(client, pid)
    r = client.post(f"/api/me/{pid}/assessment", headers=PERSON, json={"items": items})
    assert r.status_code == 422


def test_the_total_is_scored_on_the_server(client):
    """A crafted request must not be able to invent a total."""
    pid = monitor_pid(client)
    consent(client, pid)
    body = client.post(f"/api/me/{pid}/assessment", headers=PERSON, json={
        "items": MINIMAL,
        # Ignored. If this were trusted, a client could fake a severe score.
        "total": 27,
    }).json()

    assert body["total"] == 0


def test_the_ledger_records_the_total_but_never_the_answers(client):
    """An officer may not see raw psychometric responses, nor may the ledger."""
    pid = monitor_pid(client)
    consent(client, pid)
    client.post(f"/api/me/{pid}/assessment", headers=PERSON,
                json={"items": SEVERE_NOT_ACUTE})

    entries = client.get("/api/audit", headers={
        "X-Role": "auditor", "X-Operator": "AUD-01", "X-Units": "",
    }).json()["entries"]
    submitted = [e for e in entries if e["action"] == "assessment.submitted"]

    assert submitted, "the submission was not recorded at all"
    detail = submitted[-1]["detail"]
    assert detail["total"] == 21
    for key in detail:
        assert not key.startswith("item_"), f"item answers leaked into the ledger: {key}"


def test_an_acute_case_outside_the_officers_units_stays_invisible_to_them(client):
    """Unit scoping outranks urgency, and that is deliberate.

    An acute disclosure is routed to a mental-health authority regardless. What
    it does not do is put a name in front of a welfare officer who has no
    responsibility for that person — urgency is not a reason to widen who may
    see an identity, and the mental-health route is the one that carries the
    duty here.
    """
    pid = monitor_pid(client, in_officer_scope=False)
    consent(client, pid)
    before = len(caseload(client))

    body = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": MILD_BUT_ACUTE}
    ).json()

    assert body["acute"] is True
    assert body["decision"] == "IMMEDIATE_ESCALATE"
    assert body["acute_route"]["routed_to"] == "mental_health_authority"
    # Routed, and still not on this officer's screen.
    assert len(caseload(client)) == before


def test_consent_saved_through_the_api_unlocks_the_assessment(client):
    """The bug a screenshot found, as a test.

    The personnel console's "Save my choices" button set a local receipt and
    posted nothing. Every toggle read "allowed", the button read "SAVED", and
    the server had never heard of any of it — so submitting the questionnaire
    was refused for want of consent to the self-report domain. Two surfaces
    disagreeing about consent is the worst thing for them to disagree about.

    This asserts the round trip the console now performs: consent recorded
    through the API is consent the assessment route can see.
    """
    # Somebody who has never submitted a questionnaire, so bootstrap did not
    # enrol them in the self-report domain. This is the exact situation the
    # screenshot showed.
    pid = monitor_pid(client, self_report_consent=False)

    # Before: not consented to the domain, so the assessment is refused.
    refused = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": SEVERE_NOT_ACUTE}
    )
    assert refused.status_code == 403
    assert "self-report domain" in refused.json()["detail"]

    # Record it the way the console does.
    saved = client.post("/api/consent", headers=PERSON, json={
        "pid": pid,
        "locale": "en",
        "scope": ["leave", "workload", "duty_roster", "self_report"],
        "welfare_contact": True,
    })
    assert saved.status_code == 200
    body = saved.json()
    assert "self_report" in body["domains"]
    # The receipt is the server's, and it is what the console must display.
    assert body["text_version"]
    assert body["recorded_at"]

    # After: accepted.
    accepted = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": SEVERE_NOT_ACUTE}
    )
    assert accepted.status_code == 200
    assert accepted.json()["total"] == 21


def test_consent_without_self_report_still_refuses_the_assessment(client):
    """Saving the other toggles must not smuggle in the one that was refused."""
    pid = monitor_pid(client)
    client.post("/api/consent", headers=PERSON, json={
        "pid": pid,
        "locale": "en",
        "scope": ["leave", "workload", "duty_roster", "biometric", "voice"],
        "welfare_contact": True,
    })

    r = client.post(
        f"/api/me/{pid}/assessment", headers=PERSON, json={"items": SEVERE_NOT_ACUTE}
    )
    assert r.status_code == 403
