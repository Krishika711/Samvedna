"""The HTTP surface, over a real REPLAY run. Every route is an authorisation test."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from samvedna.api.app import create_app
from samvedna.api.bootstrap import build_state


@pytest.fixture(scope="module")
def world():
    state, force = build_state(units=3, strength=30, seed=771, model_dir="/nonexistent")
    return TestClient(create_app(state)), state, force


def hdr(role, operator="OP-1", units=""):
    return {"X-Role": role, "X-Operator": operator, "X-Units": units}


def an_escalated_pid(state):
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("this run produced no escalations")
    return caseload[0]


# ------------------------------------------------------------------ system --
def test_health_reports_the_config_version_and_a_verified_ledger(world):
    client, _, _ = world
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["mode"] == "replay"
    assert body["ledger_verified"] is True
    assert set(body["thresholds"]) == {
        "evidence", "consistency", "persistence", "actionability"
    }


def test_the_run_summary_contains_no_identity(world):
    client, _, force = world
    blob = str(client.get("/api/run").json())
    for person in force.personnel:
        assert person.service_number not in blob


# --------------------------------------------------------------- caseload --
def test_an_unauthenticated_request_is_refused(world):
    client, _, _ = world
    assert client.get("/api/caseload").status_code == 401


def test_a_commander_cannot_read_the_caseload(world):
    client, _, _ = world
    assert client.get("/api/caseload", headers=hdr("commander")).status_code == 403


def test_the_caseload_is_escalate_only_and_carries_no_name(world):
    client, state, force = world
    body = client.get("/api/caseload", headers=hdr("welfare_officer", "WO-1")).json()
    assert "screened" in body["headline"]
    for case in body["cases"]:
        assert case["decision"] in ("ESCALATE", "IMMEDIATE_ESCALATE")
        assert "name" not in case
        assert "service_number" not in case
    blob = str(body)
    for person in force.personnel:
        assert person.service_number not in blob


def test_every_case_carries_its_gate_formulas_with_the_numbers_substituted(world):
    client, state, _ = world
    an_escalated_pid(state)
    body = client.get("/api/caseload", headers=hdr("welfare_officer", "WO-1")).json()
    case = body["cases"][0]
    assert len(case["gates"]) == 4
    for gate in case["gates"]:
        assert gate["formula"]
        assert "=" in gate["formula"]
        assert any(ch.isdigit() for ch in gate["formula"])


def test_an_officer_only_sees_cases_in_their_own_units(world):
    client, state, _ = world
    body = client.get(
        "/api/caseload", headers=hdr("welfare_officer", "WO-1", "UNIT-01")
    ).json()
    assert all(c["unit_id"] == "UNIT-01" for c in body["cases"])


def test_case_detail_carries_the_reviewer_narratives_including_the_case_against(world):
    client, state, _ = world
    case = an_escalated_pid(state)
    body = client.get(
        f"/api/case/{case.pid}", headers=hdr("welfare_officer", "WO-1")
    ).json()
    reviewers = {r["reviewer"]: r for r in body["reviewers"]}
    assert set(reviewers) == {"risk_advocate", "confounder_check", "welfare_context"}
    assert reviewers["confounder_check"]["narrative"]


def test_a_monitor_case_is_readable_but_names_nobody(world):
    client, state, _ = world
    monitored = state.run.monitored()
    if not monitored:
        pytest.skip("no monitored cases")
    body = client.get(
        f"/api/case/{monitored[0].pid}", headers=hdr("welfare_officer", "WO-1")
    ).json()
    assert body["decision"] == "MONITOR"
    assert body["recommended"] == []
    assert body["mind_change"], "a MONITOR must say what would change its mind"


# ------------------------------------------------------------- disclosure --
def test_disclosing_an_escalated_case_returns_a_name_and_logs_it(world):
    client, state, _ = world
    case = an_escalated_pid(state)
    before = len(state.ledger)
    body = client.post(
        f"/api/case/{case.pid}/disclose", headers=hdr("welfare_officer", "WO-1")
    ).json()
    assert body["identity"]["name"]
    assert body["identity"]["service_number"]
    assert len(state.ledger) > before
    assert state.ledger.verify()[0]


def test_disclosing_a_monitor_case_is_refused(world):
    client, state, _ = world
    monitored = state.run.monitored()
    if not monitored:
        pytest.skip("no monitored cases")
    response = client.post(
        f"/api/case/{monitored[0].pid}/disclose", headers=hdr("welfare_officer", "WO-1")
    )
    assert response.status_code == 403
    assert "MONITOR" in response.json()["detail"]


def test_a_commander_cannot_disclose_anybody(world):
    client, state, _ = world
    case = an_escalated_pid(state)
    response = client.post(
        f"/api/case/{case.pid}/disclose", headers=hdr("commander", "CO-1")
    )
    assert response.status_code == 403


def test_no_commander_route_returns_a_person(world):
    """Every route a commander can reach must be checked, not just the one that
    existed when this test was written. Adding a commander route is exactly the
    change that could leak, so the test enumerates them and exercises each."""
    client, state, force = world
    commander = hdr("commander", "CO-1", "UNIT-01")

    paths = sorted(
        r.path for r in client.app.routes
        if getattr(r, "path", "").startswith("/api/unit")
    )
    assert paths == ["/api/unit/{unit_id}", "/api/unit/{unit_id}/heatmap"]

    numbers = {p.service_number for p in force.personnel}
    pids = {c.pid for c in state.run.cases}
    for path in paths:
        body = client.get(path.replace("{unit_id}", "UNIT-01"), headers=commander)
        assert body.status_code == 200, path
        blob = str(body.json())
        assert "pid" not in blob, path
        for pid in pids:
            assert pid not in blob, path
        for number in numbers:
            assert number not in blob, path


def test_the_heat_map_omits_the_domains_a_commander_has_no_lever_over(world):
    """Self-assessment, biometric and voice are the person's own. They are not
    levers a commander has, and putting them on this screen would invite the
    reading the whole design excludes."""
    client, _, _ = world
    body = client.get(
        "/api/unit/UNIT-01/heatmap", headers=hdr("commander", "CO-1", "UNIT-01")
    ).json()
    assert set(body["domains"]).isdisjoint({"self_report", "biometric", "voice"})
    assert "duty_roster" in body["domains"]


def test_a_heat_map_square_below_k_is_suppressed_not_shaded(world):
    """A shaded square covering three people is a picture of three people."""
    client, _, _ = world
    body = client.get(
        "/api/unit/UNIT-01/heatmap", headers=hdr("commander", "CO-1", "UNIT-01")
    ).json()
    for cell in body["cells"]:
        if cell["suppressed"]:
            assert cell["band"] == "suppressed"
            assert "n" not in cell
            assert "value" not in cell


def test_a_person_can_read_their_own_drivers(world):
    """PART 8.7 and the submitted trust strategy both rest on this: a person who
    is contacted can ask why, and gets the reasons the officer got."""
    client, state, _ = world
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("this run produced no escalations")
    pid = caseload[0].pid

    body = client.get(f"/api/me/{pid}/drivers", headers=hdr("personnel", pid)).json()
    assert body["assessed"] is True
    assert len(body["gates"]) == 4
    assert all(g["formula"] for g in body["gates"])
    assert "contest" in body
    assert set(body["contest"]) == {
        "factual_error", "benign_explanation", "objects_to_analysis"
    }


def test_a_person_cannot_read_somebody_elses_drivers(world):
    client, state, _ = world
    cases = state.run.cases
    if len(cases) < 2:
        pytest.skip("need two cases")
    mine, theirs = cases[0].pid, cases[1].pid
    response = client.get(f"/api/me/{theirs}/drivers", headers=hdr("personnel", mine))
    assert response.status_code == 403


def test_an_officer_cannot_use_the_personal_drivers_route(world):
    client, state, _ = world
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("no escalations")
    response = client.get(
        f"/api/me/{caseload[0].pid}/drivers", headers=hdr("welfare_officer", "WO-1")
    )
    assert response.status_code == 403


def test_withdrawal_cancels_queued_alerts(world):
    """§8.12 criterion 1, over the HTTP surface."""
    from samvedna.core.types import Gate, Verdict
    from samvedna.pipeline.record import CaseRecord

    client, state, _ = world
    gates = {
        n: Gate(n, 0.9, 0.5, True, "", {})
        for n in ("evidence", "consistency", "persistence", "actionability")
    }
    verdict = Verdict("ESCALATE", "test", gates, (), (), 0.9)
    state.alerts.enqueue(
        CaseRecord(pid="pid-alert", unit_id="UNIT-01", state="ESCALATED",
                   verdict=verdict),
        state.ledger,
    )
    assert len(state.alerts.pending()) >= 1

    body = client.post(
        "/api/consent/pid-alert/withdraw", headers=hdr("personnel", "SELF")
    ).json()
    assert body["alerts_cancelled"] >= 1
    assert not [a for a in state.alerts.pending() if a.pid == "pid-alert"]


# -------------------------------------------------------- commander view --
def test_the_commander_unit_view_is_aggregate_only(world):
    client, state, force = world
    body = client.get(
        "/api/unit/UNIT-01", headers=hdr("commander", "CO-1", "UNIT-01")
    ).json()
    assert body["k"] >= 5
    blob = str(body)
    for case in state.run.cases:
        assert case.pid not in blob
    for person in force.personnel:
        assert person.service_number not in blob
    assert "welfare officer" in body["next_step"]


def test_a_commander_cannot_read_another_units_view(world):
    client, _, _ = world
    response = client.get(
        "/api/unit/UNIT-02", headers=hdr("commander", "CO-1", "UNIT-01")
    )
    assert response.status_code == 403


def test_a_welfare_officer_cannot_use_the_commander_route(world):
    client, _, _ = world
    response = client.get(
        "/api/unit/UNIT-01", headers=hdr("welfare_officer", "WO-1", "UNIT-01")
    )
    assert response.status_code == 403


# ------------------------------------------------------------------ audit --
def test_the_auditor_sees_the_ledger_and_the_privacy_budget(world):
    client, _, _ = world
    body = client.get("/api/audit", headers=hdr("auditor", "AU-1")).json()
    assert body["verified"] is True
    assert body["entries"]
    assert "dp_budget" in body
    assert {e["action"] for e in body["entries"]} & {"verdict.recorded", "run.started"}


def test_only_an_auditor_may_read_the_ledger(world):
    client, _, _ = world
    for role in ("welfare_officer", "commander", "personnel"):
        assert client.get("/api/audit", headers=hdr(role)).status_code == 403


def test_the_ledger_shows_actor_timestamp_and_purpose_for_every_entry(world):
    """§8.12 criterion 8."""
    client, _, _ = world
    body = client.get("/api/audit", headers=hdr("auditor", "AU-1")).json()
    for entry in body["entries"]:
        assert entry["actor"]
        assert entry["at"]
        assert "purpose" in entry
        assert "entry_hash" in entry and "prev_hash" in entry


# ------------------------------------------------- personnel consent (i18n) --
def test_the_locale_list_says_which_languages_may_ground_consent(world):
    """Served rather than inferred on the client, so a UI bug cannot offer a
    draft translation as a basis for consent."""
    client, _, _ = world
    body = client.get("/api/locales").json()
    assert len(body["locales"]) >= 2
    by_code = {entry["locale"]: entry for entry in body["locales"]}
    assert by_code["en"]["may_ground_consent"] is True
    assert any(not e["may_ground_consent"] for e in body["locales"])
    assert body["pilot_mode"] is False


def test_every_language_is_offered_in_its_own_script(world):
    client, _, _ = world
    for entry in client.get("/api/locales").json()["locales"]:
        if entry["locale"] == "en":
            continue
        assert entry["name"] != entry["english_name"]


def test_recording_consent_returns_the_language_and_version_agreed_to(world):
    client, state, _ = world
    before = len(state.ledger)
    body = client.post(
        "/api/consent",
        headers=hdr("personnel", "SELF"),
        json={"pid": "pid-i18n-1", "locale": "en",
              "scope": ["leave", "duty_roster"], "welfare_contact": True},
    ).json()
    assert body["locale"] == "en"
    assert body["text_version"]
    assert body["review_status"] == "source"
    assert body["domains"] == ["duty_roster", "leave"]
    assert len(state.ledger) > before
    assert state.ledger.verify()[0]


def test_consent_against_a_draft_translation_is_refused_with_a_reason(world):
    client, _, _ = world
    response = client.post(
        "/api/consent",
        headers=hdr("personnel", "SELF"),
        json={"pid": "pid-i18n-2", "locale": "hi", "scope": ["leave"],
              "welfare_contact": True},
    )
    assert response.status_code == 422
    assert "native speaker" in response.json()["detail"]


def test_consent_against_an_unknown_language_is_refused_not_substituted(world):
    client, _, _ = world
    response = client.post(
        "/api/consent",
        headers=hdr("personnel", "SELF"),
        json={"pid": "pid-i18n-3", "locale": "xx", "scope": ["leave"],
              "welfare_contact": True},
    )
    assert response.status_code == 422
    assert "will not substitute another language" in response.json()["detail"]


def test_a_refused_consent_enrols_nobody(world):
    client, state, _ = world
    client.post(
        "/api/consent",
        headers=hdr("personnel", "SELF"),
        json={"pid": "pid-i18n-4", "locale": "ta", "scope": ["leave"],
              "welfare_contact": True},
    )
    assert state.consent.state_for("pid-i18n-4") is None


def test_only_personnel_may_record_their_own_consent(world):
    client, _, _ = world
    for role in ("welfare_officer", "commander", "auditor"):
        response = client.post(
            "/api/consent", headers=hdr(role),
            json={"pid": "x", "locale": "en", "scope": [], "welfare_contact": False},
        )
        assert response.status_code == 403


def test_consent_status_reports_the_receipt_and_whether_it_is_stale(world):
    client, _, _ = world
    client.post(
        "/api/consent", headers=hdr("personnel", "SELF"),
        json={"pid": "pid-i18n-5", "locale": "en", "scope": ["leave"],
              "welfare_contact": False},
    )
    body = client.get("/api/consent/pid-i18n-5", headers=hdr("personnel", "SELF")).json()
    assert body["enrolled"] is True
    assert body["needs_reconsent"] is False
    assert body["receipt"]["locale"] == "en"
    assert body["receipt"]["welfare_contact"] is False


def test_withdrawal_clears_the_receipt_and_is_logged(world):
    client, state, _ = world
    client.post(
        "/api/consent", headers=hdr("personnel", "SELF"),
        json={"pid": "pid-i18n-6", "locale": "en", "scope": ["leave"],
              "welfare_contact": True},
    )
    body = client.post(
        "/api/consent/pid-i18n-6/withdraw", headers=hdr("personnel", "SELF")
    ).json()
    assert body["status"] == "REVOKED"
    assert body["receipt"] is None
    assert state.consent.receipt_for("pid-i18n-6") is None
    assert state.ledger.for_action("consent.revoked")


def test_a_consent_ledger_entry_never_carries_the_consent_prose(world):
    client, state, _ = world
    client.post(
        "/api/consent", headers=hdr("personnel", "SELF"),
        json={"pid": "pid-i18n-7", "locale": "en", "scope": ["leave"],
              "welfare_contact": True},
    )
    entry = state.ledger.for_action("consent.granted")[-1]
    blob = str(entry.detail)
    assert "It can see" not in blob
    assert "commanding officer" not in blob
    assert entry.detail["locale"] == "en"


def test_a_withdrawal_ledger_entry_carries_no_detail_at_all(world):
    """PART 14 forbids surfacing that somebody withdrew. The entry records that
    an event occurred and nothing about it."""
    client, state, _ = world
    client.post(
        "/api/consent", headers=hdr("personnel", "SELF"),
        json={"pid": "pid-i18n-8", "locale": "en", "scope": ["leave"],
              "welfare_contact": True},
    )
    client.post("/api/consent/pid-i18n-8/withdraw", headers=hdr("personnel", "SELF"))
    entry = state.ledger.for_action("consent.revoked")[-1]
    assert entry.detail == {}


# ------------------------------ Workflow C, over the HTTP surface ------------
def test_the_officer_loop_runs_end_to_end(world):
    """caseload → contact → close-out, with the list blocking in between."""
    client, state, _ = world
    officer = hdr("welfare_officer", "WO-12")
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("this run produced no escalations")
    pid = caseload[0].pid

    body = client.post(f"/api/case/{pid}/contact", headers=officer).json()
    assert body["close_out_required"] is True
    assert set(body["outcomes"]) == {
        "supported", "not_supported", "already_known", "declined_contact"
    }

    after = client.get("/api/caseload", headers=officer).json()
    assert pid in after["blocking"], "a contacted case must block the list"

    closed = client.post(
        f"/api/case/{pid}/close", headers=officer, json={"outcome": "supported"}
    ).json()
    assert closed["outcome"] == "supported"
    assert closed["judged_cases"] >= 1

    final = client.get("/api/caseload", headers=officer).json()
    assert pid not in final["blocking"]
    assert final["closed"][pid] == "supported"


def test_a_case_cannot_be_closed_with_an_invented_outcome(world):
    client, state, _ = world
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("no escalations")
    response = client.post(
        f"/api/case/{caseload[0].pid}/close",
        headers=hdr("welfare_officer", "WO-12"),
        json={"outcome": "handled"},
    )
    assert response.status_code == 422
    assert "not an outcome category" in response.json()["detail"]


def test_a_deferral_without_a_reason_is_refused(world):
    client, state, _ = world
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("no escalations")
    officer = hdr("welfare_officer", "WO-12")
    pid = caseload[0].pid
    assert client.post(
        f"/api/case/{pid}/defer", headers=officer, json={"reason": "   "}
    ).status_code == 422
    assert client.post(
        f"/api/case/{pid}/defer", headers=officer, json={"reason": "on leave until the 14th"}
    ).status_code == 200


def test_only_a_welfare_officer_can_act_on_a_case(world):
    client, state, _ = world
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("no escalations")
    pid = caseload[0].pid
    for role in ("commander", "auditor", "personnel"):
        for path, body in (
            (f"/api/case/{pid}/contact", None),
            (f"/api/case/{pid}/close", {"outcome": "supported"}),
            (f"/api/case/{pid}/defer", {"reason": "x"}),
        ):
            r = client.post(path, headers=hdr(role), json=body)
            assert r.status_code == 403, f"{role} reached {path}"


def test_an_accepted_contest_suppresses_a_driver_next_run(world):
    """Workflow G over HTTP: the person disagreed, and the system stops being
    wrong about them in the same way."""
    client, state, _ = world
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("no escalations")
    pid = caseload[0].pid
    body = client.post(
        f"/api/case/{pid}/contest",
        headers=hdr("welfare_officer", "WO-12"),
        json={
            "kind": "benign_explanation",
            "driver": "leave",
            "reason": "leave was deferred at his own request for a family function",
        },
    ).json()
    assert "leave" in body["suppressed_drivers"]
    assert body["expires_on"]


def test_an_unknown_contest_kind_is_refused(world):
    client, state, _ = world
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("no escalations")
    response = client.post(
        f"/api/case/{caseload[0].pid}/contest",
        headers=hdr("welfare_officer", "WO-12"),
        json={"kind": "just_wrong", "driver": "leave", "reason": "x"},
    )
    assert response.status_code == 422


def test_every_officer_action_reaches_the_ledger(world):
    """§8.12 criterion 8, over the surface an officer actually touches."""
    client, state, _ = world
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("no escalations")
    officer = hdr("welfare_officer", "WO-12")
    pid = caseload[-1].pid

    client.post(f"/api/case/{pid}/contact", headers=officer)
    client.post(f"/api/case/{pid}/close", headers=officer, json={"outcome": "already_known"})

    actions = {e.action for e in state.ledger.for_pid(pid)}
    assert {"case.contacted", "case.closed"} <= actions
    for entry in state.ledger.for_pid(pid):
        assert entry.actor
        assert entry.at
    assert state.ledger.verify()[0]


def test_case_detail_serves_the_horizon_and_the_rhythm(world):
    """Computed, tested, and now actually on the officer's screen."""
    client, state, _ = world
    caseload = state.run.caseload()
    if not caseload:
        pytest.skip("no escalations")
    body = client.get(
        f"/api/case/{caseload[0].pid}", headers=hdr("welfare_officer", "WO-12")
    ).json()
    assert "horizon" in body and "rhythm" in body
    assert isinstance(body["horizon"]["by_days"], dict)
    assert isinstance(body["rhythm"]["features"], dict)
    # Rhythm needs no model, so its phrase must be present even in this run,
    # which is built with model_dir="/nonexistent".
    assert body["rhythm"]["phrase"]


# --------------------- the refusals, on the governance surface --------------
def test_an_auditor_can_review_what_the_system_refused_to_say(world):
    """A board that sees the escalations and not the refusals cannot tell a
    careful system from a silent one."""
    client, state, _ = world
    body = client.get("/api/refused", headers=hdr("auditor", "AU-03")).json()
    assert body["total_refused"] > 0
    assert body["monitored"] + body["no_flag"] == body["total_refused"]
    assert body["cases"]

    for case in body["cases"]:
        assert case["decision"] in ("MONITOR", "NO_FLAG")
        assert len(case["gates"]) == 4
        assert all(g["formula"] for g in case["gates"])
        assert all(g["inputs"] for g in case["gates"])


def test_the_refusals_are_ordered_nearest_miss_first(world):
    """The near misses are where the thresholds are actually doing their work."""
    client, _, _ = world
    cases = client.get("/api/refused", headers=hdr("auditor", "AU-03")).json()["cases"]
    misses = [c["closest_miss"] for c in cases]
    assert misses == sorted(misses)


def test_a_welfare_officer_cannot_read_the_refusals(world):
    """The list of people the gates declined to name is the very thing the
    refusal withheld. Handing it to an officer would undo it."""
    client, _, _ = world
    for role in ("welfare_officer", "commander", "personnel"):
        assert client.get("/api/refused", headers=hdr(role)).status_code == 403


def test_a_refusal_carries_no_identity_and_no_full_pseudonym(world):
    client, state, _ = world
    body = client.get("/api/refused", headers=hdr("auditor", "AU-03")).json()
    full_pids = {c.pid for c in state.run.cases}
    blob = str(body)
    for pid in full_pids:
        assert pid not in blob, "a refusal must not carry a resolvable pseudonym"
    for case in body["cases"]:
        assert len(case["pid"]) <= 12


def test_every_refusal_says_what_would_have_changed_it(world):
    client, _, _ = world
    cases = client.get("/api/refused", headers=hdr("auditor", "AU-03")).json()["cases"]
    with_items = [c for c in cases if c["mind_change"]]
    assert with_items, "a refusal owes an account of what it was waiting for"
    for case in with_items:
        for item in case["mind_change"]:
            assert item["would_change_if"]
            assert item["current"] <= item["required"]
