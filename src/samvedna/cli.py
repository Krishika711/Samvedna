"""Command line. `samvedna run` is the whole nightly pipeline, offline.

    samvedna run                    # a full REPLAY night on a synthetic force
    samvedna run --degrade leave    # with a connector returning partial rows
    samvedna run --break-reviewer confounder_check
    samvedna cohorts                # the three fixture cohorts through the gates
    samvedna case <pid>             # one case, with the gate arithmetic shown

Nothing here needs a database, a network, a model or a credential. That is the
point of constraint 7: no demonstration of this system may depend on live
service-record access, so the offline path is the default path and gets exercised
every time anybody runs anything.
"""
from __future__ import annotations

import argparse
import json
import sys

from samvedna.analytics.reviewers.confounder_check import ConfounderCheck
from samvedna.analytics.reviewers.panel import Panel
from samvedna.analytics.reviewers.risk_advocate import RiskAdvocate
from samvedna.analytics.reviewers.welfare_context import WelfareContext
from samvedna.config.flags import settings
from samvedna.config.weights import ALL_DOMAINS
from samvedna.core.verdict import decide
from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.consent import ConsentRegistry
from samvedna.ingest.connectors.replay import connectors_for
from samvedna.ingest.generator import generate_force
from samvedna.ingest.pseudonymise import Pseudonymiser
from samvedna.pipeline.dag import run_nightly
from samvedna.pipeline.replay import cohort_names, load_cohort

BAR = "─" * 74


class _Broken:
    """A reviewer that fails, so the freeze path is demonstrable rather than described."""

    def __init__(self, name: str) -> None:
        self.name = name

    def review(self, ctx):
        raise RuntimeError(f"{self.name} disabled from the command line")


def _panel(break_reviewer: str | None) -> Panel:
    reviewers = {
        "risk_advocate": RiskAdvocate(),
        "confounder_check": ConfounderCheck(),
        "welfare_context": WelfareContext(),
    }
    if break_reviewer:
        reviewers[break_reviewer] = _Broken(break_reviewer)
    return Panel(tuple(reviewers.values()))


def _gate_bars(verdict) -> list[str]:
    out = []
    for name, gate in verdict.gates.items():
        filled = int(round(gate.value * 20))
        mark = "PASS" if gate.passed else "FAIL"
        bar = "█" * filled + "·" * (20 - filled)
        out.append(
            f"    {name:<14} {bar} {gate.value:.3f} / {gate.threshold:.2f}  {mark}"
        )
        out.append(f"                   {gate.formula}")
    return out


def cmd_run(args) -> int:
    force = generate_force(units=args.units, strength=args.strength, seed=args.seed)
    pseudonymiser = Pseudonymiser(settings().pseudonym_salt, on=force.as_of)
    registry = ConsentRegistry()
    for person in force.personnel:
        pid = pseudonymiser.pid(person.service_number)
        # Mirror the consent the generator recorded for this person, so the
        # consent filter has something real to do rather than a blanket yes.
        scope = tuple(
            d for d in ALL_DOMAINS
            if any(r.domain == d for r in force.records if r.pid == person.service_number)
        )
        registry.enrol(pid, scope, welfare_contact=True)

    ledger = Ledger()
    drop = {args.degrade: 0.45} if args.degrade else None
    record = run_nightly(
        connectors=connectors_for(force, drop=drop),
        pseudonymiser=pseudonymiser,
        consent=registry,
        ledger=ledger,
        as_of=force.as_of,
        mode="replay",
        panel=_panel(args.break_reviewer),
        model_dir=args.model_dir,
        drift_exceeded=args.drift,
    )

    print(BAR)
    print(f"  {record.run_id}   mode={record.mode}   status={record.status}")
    print(f"  config {record.config_version}   model {record.model_version}")
    print(BAR)
    print(f"  {record.headline}")
    print(f"  monitored {record.count('MONITOR')} · no-flag {record.count('NO_FLAG')} "
          f"· cleared {record.count('CLEARED')}")
    if record.escalation_frozen:
        print(f"\n  ESCALATION FROZEN — {record.freeze_reason}")
    if record.degraded_connectors:
        print(f"  degraded connectors: {', '.join(record.degraded_connectors)}")
    if record.unavailable_reviewers:
        print(f"  unavailable reviewers: {', '.join(record.unavailable_reviewers)}")

    print(f"\n  {'stage':<14}{'status':<10}{'in':>9}{'out':>9}{'secs':>8}")
    for stage in record.stages:
        print(f"  {stage.name:<14}{stage.status:<10}{stage.rows_in:>9,}"
              f"{stage.rows_out:>9,}{stage.seconds:>8.2f}")

    caseload = record.caseload()
    print(f"\n{BAR}\n  OFFICER CASELOAD — {len(caseload)} case(s), ranked by composite")
    print(BAR)
    for case in caseload:
        v = case.verdict
        print(f"\n  {case.pid[:12]}…  {case.decision}  composite {v.composite:.3f}"
              f"  unit {case.unit_id}")
        for line in _gate_bars(v):
            print(line)
        if v.recommended:
            print(f"    recommended: {v.recommended[0].code} — {v.recommended[0].title}")
        against = next((r for r in case.reviewers if r.reviewer == "confounder_check"), None)
        if against:
            print(f"    the case against: {against.narrative[:150]}…")

    monitored = record.monitored()
    if monitored:
        example = max(monitored, key=lambda c: c.composite)
        print(f"\n{BAR}\n  A MONITOR CASE — no name is produced\n{BAR}")
        print(f"  {example.pid[:12]}…  composite {example.composite:.3f} "
              f"— {example.verdict.reason}")
        for line in _gate_bars(example.verdict):
            print(line)
        print("\n    what would change our mind:")
        for item in example.verdict.mind_change:
            print(f"      [{item.gate}] {item.current:.3f} -> needs {item.required:.2f}")
            for change in item.would_change_if:
                print(f"        · {change}")

    ok, reason = ledger.verify()
    print(f"\n{BAR}\n  audit ledger: {len(ledger)} entries · {reason}")
    print(f"  head {record.ledger_head[:32]}…\n{BAR}")
    if args.json:
        print(json.dumps(record.to_summary(), indent=2))
    return 0 if ok else 1


def cmd_cohorts(args) -> int:
    for name in cohort_names(args.fixtures):
        cohort = load_cohort(name, args.fixtures)
        print(f"\n{BAR}\n  cohort_{name} — {cohort.description}\n{BAR}")
        for ctx in cohort:
            v = decide(ctx)
            gates = " ".join(
                f"{n[:4]}{'+' if g.passed else '-'}{g.value:.2f}"
                for n, g in v.gates.items()
            )
            print(f"  {ctx.pid:<16} {v.decision:<19} {gates}   {v.reason[:38]}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from samvedna.api.app import create_app
    from samvedna.api.bootstrap import build_state

    state, _ = build_state(units=args.units, strength=args.strength, seed=args.seed)
    print(f"  {state.run.headline}")
    print(f"  {len(state.ledger)} ledger entries · {state.ledger.verify()[1]}")
    host = args.host or settings().host
    port = args.port or settings().port
    print(f"  serving on http://{host}:{port}  (REPLAY — no live records)")
    uvicorn.run(create_app(state), host=host, port=port, log_level="warning")
    return 0


def cmd_case(args) -> int:
    for name in cohort_names(args.fixtures):
        for ctx in load_cohort(name, args.fixtures):
            if ctx.pid != args.pid:
                continue
            v = decide(ctx)
            print(f"\n{BAR}\n  {ctx.pid} — {v.decision}\n  {v.reason}\n{BAR}")
            for line in _gate_bars(v):
                print(line)
            if v.mind_change:
                print("\n  what would change our mind:")
                for item in v.mind_change:
                    print(f"    [{item.gate}] {item.current:.3f} -> {item.required:.2f}"
                          f"  ({'recoverable' if item.recoverable else 'not recoverable'})")
                    for because in item.failed_because:
                        print(f"      because: {because}")
                    for change in item.would_change_if:
                        print(f"      would change if: {change}")
            for finding in Panel().review(ctx).findings:
                print(f"\n  [{finding.reviewer}] {finding.narrative}")
            return 0
    print(f"no such pid: {args.pid}", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="samvedna", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="a full nightly pipeline on a synthetic force")
    run.add_argument("--units", type=int, default=4)
    run.add_argument("--strength", type=int, default=60)
    run.add_argument("--seed", type=int, default=26186)
    run.add_argument("--degrade", metavar="DOMAIN", default=None,
                     help="make one connector return partial rows")
    run.add_argument("--break-reviewer", metavar="NAME", default=None,
                     help="disable a reviewer; confounder_check freezes escalation")
    run.add_argument("--drift", action="store_true", help="simulate model drift")
    run.add_argument("--model-dir", default="artefacts/models")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=cmd_run)

    cohorts = sub.add_parser("cohorts", help="the three fixture cohorts through the gates")
    cohorts.add_argument("--fixtures", default="fixtures")
    cohorts.set_defaults(func=cmd_cohorts)

    serve = sub.add_parser("serve", help="run the API over a fresh REPLAY night")
    serve.add_argument("--units", type=int, default=4)
    serve.add_argument("--strength", type=int, default=60)
    serve.add_argument("--seed", type=int, default=26186)
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(func=cmd_serve)

    case = sub.add_parser("case", help="one case, with the gate arithmetic shown")
    case.add_argument("pid")
    case.add_argument("--fixtures", default="fixtures")
    case.set_defaults(func=cmd_case)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
