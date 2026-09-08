"""Phase 6 ship gate: verdict changes when a confounder appears — and the panel
fails safely.
"""
from __future__ import annotations

import time

from tests.conftest import case, consent, deviation, unit

from samvedna.analytics.reviewers.base import REVIEWER_NAMES, unavailable_finding
from samvedna.analytics.reviewers.confounder_check import ConfounderCheck
from samvedna.analytics.reviewers.panel import Panel, default_panel
from samvedna.analytics.reviewers.risk_advocate import RiskAdvocate
from samvedna.analytics.reviewers.welfare_context import WelfareContext
from samvedna.core.verdict import decide

SUSTAINED = {7: 1.0, 30: 1.0, 90: 0.9}


def clean_case():
    return case(
        deviation("self_report", breach=SUSTAINED),
        deviation("leave", breach=SUSTAINED),
        deviation("duty_roster", breach=SUSTAINED),
    )


def confounded_case():
    return case(
        deviation("self_report", breach=SUSTAINED),
        deviation("leave", breach=SUSTAINED),
        deviation("duty_roster", breach=SUSTAINED),
        unit_state=unit(
            deviating={"self_report": 0.45, "leave": 0.52, "duty_roster": 0.61}
        ),
    )


# --------------------------------------------------------------- ship gate --
def test_the_verdict_changes_when_a_confounder_appears():
    """Same person, same deviations, same persistence. The only difference is
    that the unit moved with them — and the system stops naming them."""
    assert decide(clean_case()).decision == "ESCALATE"
    assert decide(confounded_case()).decision == "MONITOR"


def test_the_reviewer_and_the_gate_report_the_same_facts():
    """The narrative explains the arithmetic rather than competing with it."""
    ctx = confounded_case()
    finding = ConfounderCheck().review(ctx)
    verdict = decide(ctx)
    assert "unit_op_tempo" in finding.confounders_found
    assert "unit_op_tempo" in verdict.gates["consistency"].inputs["confounders"]
    assert "0.70" in finding.narrative
    assert "0.70" in " ".join(
        s for i in verdict.mind_change for s in i.would_change_if
    )


# ------------------------------------------------------------------- panel --
def test_all_three_reviewers_return_a_finding():
    result = Panel().review(clean_case())
    assert tuple(f.reviewer for f in result.findings) == REVIEWER_NAMES
    assert all(f.status == "ok" for f in result.findings)


def test_the_panel_runs_them_in_parallel():
    class Slow:
        def __init__(self, name):
            self.name = name

        def review(self, ctx):
            time.sleep(0.25)
            return unavailable_finding(self.name, "slept")

    panel = Panel(tuple(Slow(n) for n in REVIEWER_NAMES), timeout_s=5)
    started = time.perf_counter()
    panel.review(clean_case())
    elapsed = time.perf_counter() - started
    assert elapsed < 0.6, f"three 0.25s reviewers took {elapsed:.2f}s; that is serial"


def test_a_broken_reviewer_does_not_break_the_run():
    class Broken:
        name = "confounder_check"

        def review(self, ctx):
            raise RuntimeError("records service down")

    result = Panel((RiskAdvocate(), Broken(), WelfareContext())).review(clean_case())
    assert result.unavailable == ("confounder_check",)
    assert result.by_name("risk_advocate").status == "ok"


def test_a_broken_reviewer_never_fabricates_a_finding():
    finding = unavailable_finding("confounder_check", "timed out")
    assert finding.status == "unavailable"
    assert finding.confounders_found == ()
    assert finding.domain_assessments == ()
    assert "none has been assumed" in finding.narrative


def test_a_timeout_is_reported_as_unavailable_not_as_no_confounders():
    class Hang:
        name = "confounder_check"

        def review(self, ctx):
            time.sleep(2)
            return unavailable_finding(self.name)

    result = Panel((Hang(),), timeout_s=0.1).review(clean_case())
    assert result.freeze_escalation


def test_a_missing_reviewer_is_unavailable_not_absent():
    """The officer must see three panels, one of which says it did not run."""
    result = Panel((RiskAdvocate(),)).review(clean_case())
    assert len(result.findings) == 3
    assert set(result.unavailable) == {"confounder_check", "welfare_context"}


# --------------------------------------------------- the freeze (PART 8.8) --
def test_without_the_confounder_check_the_run_produces_no_escalate_at_all():
    """§8.12 criterion 5, verified end to end: with Confounder Check forcibly
    disabled, a case that would otherwise ESCALATE lands on MONITOR."""
    class Broken:
        name = "confounder_check"

        def review(self, ctx):
            raise RuntimeError("disabled for this test")

    result = Panel((RiskAdvocate(), Broken(), WelfareContext())).review(clean_case())
    assert result.freeze_escalation

    frozen = decide(clean_case(), escalation_frozen=result.freeze_escalation)
    assert frozen.decision == "MONITOR"
    assert "frozen" in frozen.reason
    assert all(g.passed for g in frozen.gates.values()), (
        "the gates still ran and still passed; only the naming is withheld"
    )


def test_losing_a_different_reviewer_does_not_freeze_escalation():
    """Only the case *against* is load-bearing for the freeze."""
    class Broken:
        name = "welfare_context"

        def review(self, ctx):
            raise RuntimeError("down")

    result = Panel((RiskAdvocate(), ConfounderCheck(), Broken())).review(clean_case())
    assert result.unavailable == ("welfare_context",)
    assert not result.freeze_escalation


# ------------------------------------------------------------- narratives --
def test_no_reviewer_emits_a_gate_value_a_verdict_or_a_confidence():
    """PART 14: no model, LLM or heuristic may emit any of these."""
    forbidden = ("escalate", "no_flag", "verdict", "% confident", "confidence of",
                 "gate value", "we recommend escalating")
    for ctx in (clean_case(), confounded_case()):
        for finding in Panel().review(ctx).findings:
            text = finding.narrative.lower()
            for phrase in forbidden:
                assert phrase not in text, f"{finding.reviewer} said {phrase!r}"


def test_the_advocate_argues_only_from_deviations_that_exist():
    ctx = case(deviation("leave", breach=SUSTAINED))
    finding = RiskAdvocate().review(ctx)
    assert "leave" in finding.narrative
    assert "duty" not in finding.narrative.lower()
    assert {d for d, _, _ in finding.domain_assessments} == {"leave"}


def test_the_advocate_has_no_case_when_consent_covers_nothing():
    ctx = case(deviation("leave"), consent_state=consent(scope=(), status="REVOKED"))
    finding = RiskAdvocate().review(ctx)
    assert "no case to make" in finding.narrative.lower()


def test_welfare_context_surfaces_an_unsuccessful_precedent_as_a_caution():
    """The most useful thing this reviewer can hand an officer is a similar case
    that did NOT turn out to be a welfare issue."""
    ctx = case(
        deviation("duty_roster"), deviation("leave"), deviation("workload")
    )
    finding = WelfareContext().review(ctx)
    assert "Caution" in finding.narrative
    assert "not_supported" in finding.narrative


def test_welfare_context_warns_about_an_active_intervention():
    from samvedna.core.interventions import BY_CODE

    ctx = case(deviation("leave"), active=(BY_CODE["WLF-LEAVE"],))
    finding = WelfareContext().review(ctx)
    assert "active intervention" in finding.narrative


def test_no_reviewer_module_can_reach_an_external_endpoint():
    """PART 1 and PART 10 forbid external processing of this data class."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    package = root / "src" / "samvedna" / "analytics" / "reviewers"
    banned = {"httpx", "requests", "urllib", "openai", "anthropic", "socket", "http"}
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                assert name not in banned, f"{path.name} imports {name}"


def test_the_default_panel_is_the_three_named_reviewers():
    assert tuple(r.name for r in default_panel()) == REVIEWER_NAMES
