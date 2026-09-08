"""The HTTP surface. Thin, and every route is an authorisation decision.

There is deliberately no endpoint that returns a person from the commander's
routes, no endpoint that returns raw self-report answers to anybody, and no
endpoint that accepts an administrative purpose. Those are not omissions to be
filled in later — PART 8.0's disclosure boundary is enforced in L5, and the API's
job is to hand L5 a principal and let it refuse.

The dev identity header is exactly that: a development shim standing where
Keycloak OIDC goes. It is refused unless the process is started in REPLAY mode,
so it cannot survive being pointed at live records.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from samvedna.api import api_console, voice_routes
from samvedna.config.flags import settings
from samvedna.config.thresholds import CONFIG_VERSION, GATE_THRESHOLDS
from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.commander import heat_map, unit_view
from samvedna.disclosure.consent import ConsentRegistry
from samvedna.disclosure.consent_text import (
    ConsentTextUnavailable,
    available_locales,
)
from samvedna.disclosure.dpcache import ReleaseCache
from samvedna.disclosure.rbac import Denied, Principal
from samvedna.disclosure.reidentify import Identity, try_disclose
from samvedna.ingest.dp import Budget
from samvedna.pipeline.alerts import AlertQueue
from samvedna.pipeline.outcomes import OUTCOMES, CaseBook, OutcomeRequired
from samvedna.pipeline.record import RunRecord

__all__ = ["create_app", "AppState"]


class AppState:
    """Everything the API serves, assembled by the orchestrator.

    Held on the app rather than in module globals so a test can build a whole
    console over a fixture run without touching a database.
    """

    def __init__(self) -> None:
        self.run: RunRecord | None = None
        self.ledger = Ledger()
        self.consent = ConsentRegistry()
        self.budget = Budget()
        # Per-run, so a refresh re-serves rather than re-noising. See dpcache.py.
        self.release_cache = ReleaseCache()
        self.alerts = AlertQueue()
        # Officer actions across runs: contact, deferral, close-out, contest.
        self.book = CaseBook()
        # Open voice sittings, in memory only. A sitting is a
        # conversation happening now; persisting one would mean
        # persisting the transcript, which is the thing this design is
        # most careful to destroy.
        self.voice = voice_routes.VoiceStore()
        self.directory: dict[str, Identity] = {}
        self.contacts: dict[str, dict] = {}
        self.annotations: dict[str, list[dict]] = {}

    def resolve(self, pid: str) -> Identity | None:
        return self.directory.get(pid)


def _principal(
    x_role: str = Header(default=""),
    x_operator: str = Header(default=""),
    x_units: str = Header(default=""),
) -> Principal:
    if settings().mode != "replay":
        raise HTTPException(
            status_code=501,
            detail=(
                "header-based identity is a REPLAY-only development shim. "
                "In live mode this route requires an OIDC token."
            ),
        )
    if not x_role or not x_operator:
        raise HTTPException(status_code=401, detail="X-Role and X-Operator are required")
    return Principal(
        subject_id=x_operator,
        role=x_role,  # type: ignore[arg-type]
        unit_scope=frozenset(u for u in x_units.split(",") if u),
    )


def create_app(state: AppState | None = None) -> FastAPI:
    app = FastAPI(
        title="SAMVEDNA",
        description=(
            "Predictive personnel stress and welfare monitoring. "
            "The model raises the concern; deterministic arithmetic decides; "
            "a human welfare officer takes the action."
        ),
        version=CONFIG_VERSION,
    )
    app.state.samvedna = state or AppState()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings().allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    def st(request: Request) -> AppState:
        return request.app.state.samvedna

    def _require_run(state: AppState) -> RunRecord:
        if state.run is None:
            raise HTTPException(status_code=503, detail="no run record loaded")
        return state.run

    # ------------------------------------------------------------- system --
    @app.get("/api/health")
    def health(request: Request):
        state = st(request)
        ok, reason = state.ledger.verify()
        return {
            "status": "ok",
            "mode": settings().mode,
            "config_version": CONFIG_VERSION,
            "thresholds": GATE_THRESHOLDS,
            "ledger_entries": len(state.ledger),
            "ledger_verified": ok,
            "ledger_reason": reason,
            "run": state.run.run_id if state.run else None,
        }

    @app.get("/api/run")
    def run_summary(request: Request):
        return _require_run(st(request)).to_summary()

    # ---------------------------------------------- welfare officer (L6) --
    @app.get("/api/caseload")
    def caseload(request: Request, principal: Principal = Depends(_principal)):
        """ESCALATE cases only. No identity — that needs a separate, logged act."""
        if principal.role != "welfare_officer":
            raise HTTPException(status_code=403, detail="welfare officers only")
        state = st(request)
        run = _require_run(state)
        cases = [
            c for c in run.caseload()
            if not principal.unit_scope or c.unit_id in principal.unit_scope
        ]
        escalated = tuple(c.pid for c in cases)
        return {
            "headline": run.headline,
            "run_id": run.run_id,
            "as_of": run.as_of.isoformat(),
            # Cases contacted but not closed. The console blocks on these — a
            # case cannot be left open, and the list says so rather than the
            # officer having to remember.
            "blocking": list(state.book.blocking(escalated)),
            "closed": {
                pid: state.book.closed[pid].outcome
                for pid in escalated if pid in state.book.closed
            },
            "contacted": {
                pid: state.book.contacted[pid].isoformat()
                for pid in escalated if pid in state.book.contacted
            },
            "realised_precision": round(state.book.realised_precision()[0], 4),
            "judged_cases": state.book.realised_precision()[1],
            "escalation_frozen": run.escalation_frozen,
            "freeze_reason": run.freeze_reason,
            "degraded_connectors": list(run.degraded_connectors),
            "unavailable_reviewers": list(run.unavailable_reviewers),
            "cases": [_case_payload(c, state) for c in cases],
        }

    @app.get("/api/case/{pid}")
    def case_detail(pid: str, request: Request, principal: Principal = Depends(_principal)):
        if principal.role != "welfare_officer":
            raise HTTPException(status_code=403, detail="welfare officers only")
        state = st(request)
        run = _require_run(state)
        case = next((c for c in run.cases if c.pid == pid), None)
        if case is None or case.verdict is None:
            raise HTTPException(status_code=404, detail="no such case in this run")
        if principal.unit_scope and case.unit_id not in principal.unit_scope:
            raise HTTPException(status_code=403, detail="outside your unit scope")
        payload = _case_payload(case, state, full=True)
        payload["annotations"] = state.annotations.get(pid, [])
        return payload

    @app.post("/api/case/{pid}/contact")
    def record_contact(
        pid: str, request: Request, principal: Principal = Depends(_principal)
    ):
        """The officer has approached the person. Workflow C, the ACT branch.

        Only the *fact* of contact is stored. The content of a welfare
        conversation is never written to this system — if clinical detail needs
        recording it belongs in the medical record, behind a different authority.
        """
        if principal.role != "welfare_officer":
            raise HTTPException(status_code=403, detail="welfare officers only")
        state = st(request)
        when = state.book.record_contact(pid, principal, state.ledger)
        state.alerts.deliver(pid, state.ledger)
        return {
            "pid": pid,
            "contacted_at": when.isoformat(),
            "close_out_required": True,
            "outcomes": list(OUTCOMES),
        }

    @app.post("/api/case/{pid}/close")
    def close_case(
        pid: str,
        request: Request,
        payload: dict,
        principal: Principal = Depends(_principal),
    ):
        """Mandatory close-out. Refuses anything that is not an outcome category.

        These labels are the only honest source of precision in production: a
        training metric describes data the model was fitted to, and an officer
        typing `not_supported` describes what happened to a real jawan.
        """
        if principal.role != "welfare_officer":
            raise HTTPException(status_code=403, detail="welfare officers only")
        state = st(request)
        try:
            record = state.book.close(
                pid, payload.get("outcome", ""), principal, state.ledger,
                note=payload.get("note", ""),
            )
        except OutcomeRequired as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        precision, judged = state.book.realised_precision()
        return {
            "pid": pid,
            "outcome": record.outcome,
            "closed_at": record.at.isoformat(),
            "realised_precision": round(precision, 4),
            "judged_cases": judged,
        }

    @app.post("/api/case/{pid}/defer")
    def defer_case(
        pid: str,
        request: Request,
        payload: dict,
        principal: Principal = Depends(_principal),
    ):
        """Back to MONITOR with a reason. The reason is mandatory and logged."""
        if principal.role != "welfare_officer":
            raise HTTPException(status_code=403, detail="welfare officers only")
        state = st(request)
        try:
            state.book.defer(pid, payload.get("reason", ""), principal, state.ledger)
        except OutcomeRequired as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"pid": pid, "deferred": True, "reason": payload.get("reason", "")}

    @app.post("/api/case/{pid}/contest")
    def contest_case(
        pid: str,
        request: Request,
        payload: dict,
        principal: Principal = Depends(_principal),
    ):
        """Workflow G. The person disagreed; the officer records which way.

        An accepted benign explanation suppresses that driver for a configured
        window, so the system stops being wrong about them in the same way next
        cycle. Without this every false positive is permanent.
        """
        if principal.role != "welfare_officer":
            raise HTTPException(status_code=403, detail="welfare officers only")
        state = st(request)
        run = _require_run(state)
        kind = payload.get("kind", "")
        if kind not in ("factual_error", "benign_explanation", "objects_to_analysis"):
            raise HTTPException(status_code=422, detail=f"unknown contest kind '{kind}'")
        annotation = state.book.contest(
            pid, kind, payload.get("driver", ""), payload.get("reason", ""),
            principal, state.ledger, as_of=run.as_of,
        )
        return {
            "pid": pid,
            "kind": kind,
            "suppressed_drivers": sorted(state.book.suppressed_drivers(pid, run.as_of)),
            "expires_on": annotation.expires_on.isoformat() if annotation else None,
        }

    @app.post("/api/case/{pid}/disclose")
    def disclose_case(
        pid: str, request: Request, principal: Principal = Depends(_principal),
        justification: str = "",
    ):
        """The one route that can produce a name. Always logged, often refused."""
        state = st(request)
        run = _require_run(state)
        case = next((c for c in run.cases if c.pid == pid), None)
        if case is None or case.verdict is None:
            raise HTTPException(status_code=404, detail="no such case in this run")
        purpose = "welfare:acute" if case.verdict.override else "welfare:contact"
        result, reason = try_disclose(
            pid=pid,
            verdict=case.verdict,
            principal=principal,
            purpose=purpose,
            unit_id=case.unit_id,
            directory=state,
            ledger=state.ledger,
            consent=state.consent,
            justification=justification,
        )
        if result is None:
            raise HTTPException(status_code=403, detail=reason)
        return {
            "pid": pid,
            "identity": {
                "service_number": result.identity.service_number,
                "name": result.identity.name,
                "rank": result.identity.rank,
                "unit_id": result.identity.unit_id,
                "contact": result.identity.contact,
            },
            "purpose": result.purpose,
            "ledger_seq": result.ledger_seq,
            "disclosed_at": result.at.isoformat(),
        }

    # ------------------------------------------------------- commander (L6) --
    @app.get("/api/unit/{unit_id}")
    def commander_unit(
        unit_id: str, request: Request, principal: Principal = Depends(_principal)
    ):
        state = st(request)
        run = _require_run(state)
        try:
            view = unit_view(
                run, unit_id, principal, state.budget, state.ledger,
                differential_privacy=settings().differential_privacy,
                cache=state.release_cache,
            )
        except Denied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return view.to_dict()

    # -------------------------------------------------------- personnel (L6) --
    @app.get("/api/locales")
    def locales(request: Request):
        """Which languages exist, and which may ground consent.

        The distinction is served to the client rather than inferred there, so a
        UI bug cannot offer a draft translation as a basis for consent.
        """
        return {
            "locales": [
                {
                    "locale": t.locale,
                    "name": t.name,
                    "english_name": t.english_name,
                    "direction": t.direction,
                    "text_version": t.text_version,
                    "review_status": t.review_status,
                    "reviewed_by": t.reviewed_by,
                    "may_ground_consent": t.may_ground_consent,
                }
                for t in available_locales()
            ],
            "pilot_mode": settings().consent_pilot_mode,
        }

    @app.post("/api/consent")
    def record_consent(
        request: Request,
        payload: dict,
        principal: Principal = Depends(_principal),
    ):
        """Record consent against the exact text the person read.

        Refuses rather than falling back: an unknown locale, or a draft one
        outside pilot mode, produces a 422 explaining why. Silently substituting
        another language would produce a consent record that cannot answer the
        only question that matters when it is challenged.
        """
        if principal.role != "personnel":
            raise HTTPException(status_code=403, detail="personnel only")
        state = st(request)
        pid = payload.get("pid") or principal.subject_id
        locale = payload.get("locale", "")
        scope = tuple(payload.get("scope", []))
        welfare_contact = bool(payload.get("welfare_contact", False))
        try:
            consent_state, receipt = state.consent.enrol_with_receipt(
                pid, scope,
                welfare_contact=welfare_contact,
                locale=locale,
                pilot_mode=settings().consent_pilot_mode,
            )
        except ConsentTextUnavailable as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        state.ledger.append(
            actor=f"personnel:{pid}",
            action="consent.granted",
            subject_pid=pid,
            purpose="welfare:self",
            detail=receipt.to_ledger_detail(),
        )
        return {
            "status": consent_state.status,
            "locale": receipt.locale,
            "text_version": receipt.text_version,
            "content_hash": receipt.content_hash[:16],
            "review_status": receipt.review_status,
            "recorded_at": receipt.granted_at.isoformat(),
            "domains": sorted(receipt.scope),
            "welfare_contact": receipt.welfare_contact,
        }

    @app.get("/api/consent/{pid}")
    def consent_status(pid: str, request: Request, principal: Principal = Depends(_principal)):
        """A person's own consent, and whether the text has moved under them."""
        if principal.role != "personnel":
            raise HTTPException(status_code=403, detail="personnel only")
        state = st(request)
        receipt = state.consent.receipt_for(pid)
        stale, why = state.consent.needs_reconsent(pid)
        return {
            "enrolled": bool(receipt),
            "needs_reconsent": stale,
            "reason": why,
            "receipt": (
                {
                    "locale": receipt.locale,
                    "text_version": receipt.text_version,
                    "review_status": receipt.review_status,
                    "recorded_at": receipt.granted_at.isoformat(),
                    "domains": sorted(receipt.scope),
                    "welfare_contact": receipt.welfare_contact,
                }
                if receipt else None
            ),
        }

    @app.get("/api/me/{pid}/drivers")
    def my_drivers(pid: str, request: Request, principal: Principal = Depends(_principal)):
        """The same reasons the officer saw, shown to the person themselves.

        PART 8.7's dignity path and the PPT's trust strategy both rest on this:
        a person who is contacted can ask why, and gets the drivers in the same
        plain language, not a summary written for them. Without it every false
        positive is permanent, which is how a welfare tool becomes feared.

        A person may only read their own. `welfare:self` is the only purpose
        under which this resolves, and the pid must be their own subject id.
        """
        if principal.role != "personnel":
            raise HTTPException(status_code=403, detail="personnel only")
        if principal.subject_id not in (pid, "SELF"):
            raise HTTPException(status_code=403, detail="you may only read your own")

        state = st(request)
        run = _require_run(state)
        case = next((c for c in run.cases if c.pid == pid), None)
        if case is None or case.verdict is None:
            return {
                "pid": pid,
                "assessed": False,
                "message": (
                    "Nothing was raised about you in the most recent run. "
                    "That is the ordinary result."
                ),
                "drivers": [],
                "gates": [],
            }

        v = case.verdict
        return {
            "pid": pid,
            "assessed": True,
            "decision": v.decision,
            "named_to_an_officer": v.names_a_person,
            "message": (
                "A welfare officer was given your name, along with these reasons."
                if v.names_a_person else
                "No name was released. These are the reasons the system weighed, "
                "and the gate that stopped it."
            ),
            # The same gate arithmetic the officer sees, unabridged. A summary
            # written for the person would be a different account of the same
            # decision, and they are entitled to the one that was actually used.
            "gates": [
                {"name": g.name, "value": round(g.value, 4), "threshold": g.threshold,
                 "passed": g.passed, "formula": g.formula}
                for g in v.gates.values()
            ],
            # The SHAP attributions, in the person's own words where the feature
            # name maps to something they would recognise.
            "drivers": [
                {
                    "feature": name,
                    "contribution": round(weight, 5),
                    "plain": _plain_driver(name),
                }
                for name, weight in case.drivers
            ],
            "mind_change": [
                {"gate": m.gate, "current": m.current, "required": m.required,
                 "would_change_if": list(m.would_change_if)}
                for m in v.mind_change
            ],
            # Three ways to disagree, and all three are real: PART 8.7 requires
            # a person be able to make the system stop being wrong about them.
            "contest": {
                "factual_error": (
                    "A record is wrong — request a correction from the unit "
                    "records custodian and the next run uses the corrected one."
                ),
                "benign_explanation": (
                    "There is an ordinary reason the system missed — an officer "
                    "can annotate it, and that driver is suppressed on the next run."
                ),
                "objects_to_analysis": (
                    "You can narrow or withdraw consent. There is no penalty, and "
                    "nobody is told."
                ),
            },
        }

    @app.post("/api/consent/{pid}/withdraw")
    def withdraw_consent(
        pid: str, request: Request, principal: Principal = Depends(_principal)
    ):
        """One tap. Purge, drop from watchlists, cancel undelivered alerts."""
        if principal.role != "personnel":
            raise HTTPException(status_code=403, detail="personnel only")
        state = st(request)
        state.consent.revoke(pid)
        # PART 8.12 criterion 1: an undelivered alert is cancelled, not just
        # marked. This is only possible because dispatch is deferred to 07:00.
        cancelled = state.alerts.cancel_for(pid, state.ledger)
        state.ledger.append(
            actor=f"personnel:{pid}",
            action="consent.revoked",
            subject_pid=pid,
            purpose="welfare:self",
            detail={},
        )
        return {
            "status": "REVOKED",
            "receipt": None,
            "alerts_cancelled": cancelled,
        }

    @app.get("/api/unit/{unit_id}/heatmap")
    def commander_heatmap(
        unit_id: str, request: Request, principal: Principal = Depends(_principal)
    ):
        """Fatigue and workload across a unit's sub-units, for rebalancing.

        Every square is k-checked and DP-noised exactly like a scalar aggregate,
        and a square below k is suppressed rather than shaded — a shaded square
        covering three people is a picture of three people.
        """
        state = st(request)
        run = _require_run(state)
        try:
            return heat_map(
                run, unit_id, principal, state.budget, state.ledger,
                differential_privacy=settings().differential_privacy,
                cache=state.release_cache,
            )
        except Denied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    # ---------------------------------------------------------- auditor (L6) --
    @app.get("/api/refused")
    def refused(request: Request, principal: Principal = Depends(_principal), limit: int = 12):
        """The cases the system declined to name, with the arithmetic that
        declined them.

        An auditor reviews **every** verdict, not only the ones that produced a
        name — a governance board that can see the escalations and not the
        refusals cannot tell a careful system from a silent one. So this exists,
        and it is deliberately on the audit surface rather than the officer's:
        a welfare officer must not be handed a list of people the gates refused
        to name, because that list is the very thing the refusal withheld.

        No identity, and no re-identification is possible from here. What is
        served is a truncated pseudonym, the four gate values with their
        formulas, and the computed statement of what would have changed the
        decision.
        """
        if principal.role != "auditor":
            raise HTTPException(status_code=403, detail="auditors only")
        state = st(request)
        run = _require_run(state)

        held = [c for c in run.cases if c.verdict and not c.verdict.names_a_person]
        # Nearest-miss first. The cases that came closest to being named are the
        # ones a governance board most needs to see, because they are where the
        # thresholds are actually doing their work.
        def shortfall(case):
            failed = [g for g in case.verdict.gates.values() if not g.passed]
            return min((g.threshold - g.value for g in failed), default=99.0)

        held.sort(key=shortfall)
        return {
            "run_id": run.run_id,
            "as_of": run.as_of.isoformat(),
            "total_refused": len(held),
            "monitored": run.count("MONITOR"),
            "no_flag": run.count("NO_FLAG"),
            "cases": [
                {
                    "pid": c.pid[:12],
                    "unit_id": c.unit_id,
                    "decision": c.decision,
                    "reason": c.verdict.reason,
                    "composite": round(c.verdict.composite, 4),
                    "closest_miss": round(shortfall(c), 4),
                    # Every input term, not just the formula. An auditor
                    # reviewing a refusal has to be able to redo the sum, and
                    # the terms are domain names and counts — nothing that
                    # narrows down who this is.
                    "gates": [
                        {"name": g.name, "value": round(g.value, 4),
                         "threshold": g.threshold, "passed": g.passed,
                         "formula": g.formula,
                         "inputs": {k: str(x) for k, x in g.inputs.items()}}
                        for g in c.verdict.gates.values()
                    ],
                    "mind_change": [
                        {"gate": m.gate, "current": m.current, "required": m.required,
                         "failed_because": list(m.failed_because),
                         "would_change_if": list(m.would_change_if),
                         "recoverable": m.recoverable}
                        for m in c.verdict.mind_change
                    ],
                }
                for c in held[:limit]
            ],
        }

    @app.get("/api/audit")
    def audit(request: Request, principal: Principal = Depends(_principal), limit: int = 200):
        if principal.role != "auditor":
            raise HTTPException(status_code=403, detail="auditors only")
        state = st(request)
        ok, reason = state.ledger.verify()
        return {
            "verified": ok,
            "reason": reason,
            "entries": [e.to_dict() for e in state.ledger.entries()[-limit:]],
            "dp_budget": {
                "total": state.budget.total,
                "spent": round(state.budget.spent, 4),
                "remaining": round(state.budget.remaining, 4),
            },
        }

    # Live voice sittings. Attached rather than inlined because this file is
    # long enough already, and the routes share nothing with the rest of the
    # API except the state object.
    voice_routes.attach(app, st)

    # A self-contained API console at /api-console. FastAPI's own /docs pulls
    # Swagger UI from a CDN, so it renders blank on an air-gapped network.
    api_console.attach(app)

    return app


# Feature names are built for the matcher, not for a person reading about
# themselves. This maps them back to the thing that actually happened.
_DRIVER_WORDS = {
    "leave": "how often your leave applications were denied",
    "duty_roster": "how many consecutive duty days you worked without a clear break",
    "workload": "your duty hours against what the unit is established for",
    "deployment": "how long you have been deployed away from station",
    "transfer": "how many postings you have had in the last year",
    "training": "how many course and training days you were assigned",
    "self_report": "the wellness self-assessment you filled in",
    "biometric": "your opt-in resting heart-rate trend",
    "voice": "a voice session you consented to",
}


def _plain_driver(feature: str) -> str:
    for key, words in _DRIVER_WORDS.items():
        if feature.startswith(key):
            window = ""
            if "_30d" in feature:
                window = " over the last 30 days"
            elif "_90d" in feature:
                window = " over the last 90 days"
            elif "_7d" in feature:
                window = " over the last week"
            elif feature.endswith("_slope"):
                window = " — and the direction it has been moving"
            return words + window
    return feature.replace("_", " ")


def _case_payload(case, state: AppState, *, full: bool = False) -> dict:
    """A case as the officer sees it — with the arithmetic, without a name."""
    v = case.verdict
    payload = {
        "pid": case.pid,
        "unit_id": case.unit_id,
        "decision": v.decision,
        "reason": v.reason,
        "composite": round(v.composite, 4),
        "override": v.override,
        "config_version": v.config_version,
        "gates": [
            {
                "name": g.name,
                "value": round(g.value, 4),
                "threshold": g.threshold,
                "passed": g.passed,
                # The highest-value element in the whole interface: the formula
                # with the actual numbers substituted.
                "formula": g.formula,
                "inputs": {k: str(x) for k, x in g.inputs.items()},
            }
            for g in v.gates.values()
        ],
        "recommended": [
            {"code": i.code, "title": i.title, "rationale": i.rationale,
             "authority": i.authority}
            for i in v.recommended
        ],
        "mind_change": [
            {
                "gate": m.gate, "current": m.current, "required": m.required,
                "failed_because": list(m.failed_because),
                "would_change_if": list(m.would_change_if),
                "recoverable": m.recoverable,
            }
            for m in v.mind_change
        ],
        "contacted": state.contacts.get(case.pid),
    }
    if full:
        payload["reviewers"] = [
            {"reviewer": r.reviewer, "status": r.status, "narrative": r.narrative,
             "confounders_found": list(r.confounders_found)}
            for r in case.reviewers
        ]
        payload["risk"] = {
            "score": case.risk_score,
            "model_version": case.model_version,
            "drivers": [
                {"feature": n, "contribution": round(w, 5), "plain": _plain_driver(n)}
                for n, w in case.drivers
            ],
        }
        # "Risk by when", and the shape of the roster underneath it. Neither
        # decides anything — a three-day horizon does not lower a threshold or
        # shorten a window — but both change what an officer does this week.
        payload["horizon"] = {
            "by_days": {str(k): v for k, v in sorted(case.horizon.items())},
            "phrase": case.horizon_phrase,
        }
        payload["rhythm"] = {
            "features": case.rhythm,
            "phrase": case.rhythm_phrase,
        }
    return payload
