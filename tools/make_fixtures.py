#!/usr/bin/env python3
"""Author the three fixture cohorts of PART 13.

Deterministic: a fixed seed, no clock, no network. Re-running it must reproduce
the files byte for byte, because a fixture that drifts is a test that stops
meaning anything.

Each person carries an `expected` verdict. That field is for the *test suite*
only — `pipeline/replay.py` refuses to read it, and a test asserts that it does.
PART 1 constraint 8 is explicit that the MONITOR path must be produced by the
gate engine on real fixture data and never by a demo branch, and the only way to
be sure of that is for the fixture's answer to be unreachable from the pipeline.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures"
SEED = 26186  # the problem statement number; arbitrary but fixed

SUSTAINED = {"7": 1.0, "30": 1.0, "90": 0.9}
MONTH = {"7": 1.0, "30": 1.0, "90": 0.2}
BLIP = {"7": 1.0, "30": round(7 / 30, 6), "90": round(7 / 90, 6)}
QUIET = {"7": 0.0, "30": 0.05, "90": 0.02}

ALL_SCOPE = ["leave", "deployment", "duty_roster", "transfer", "training",
             "workload", "self_report", "biometric"]
RECORDS_ONLY = ["leave", "deployment", "duty_roster", "transfer", "training", "workload"]


def dev(domain, breach, *, z_self=2.8, z_unit=2.2, direction="elevated", missing=0.0,
        windows=3):
    return {
        "domain": domain,
        "z_self": z_self,
        "z_unit": z_unit,
        "direction": direction,
        "windows_breached": windows,
        "daily_breach": breach,
        "missing_fraction": missing,
    }


def unit_block(cohort_size, deviating=None, *, leave=(), training=(), seasonal=(),
               capacity=True, unit_id="UNIT-7RB"):
    return {
        "unit_id": unit_id,
        "cohort_size": cohort_size,
        "cohort_deviating_fraction": deviating or {},
        "sanctioned_leave_domains": list(leave),
        "training_domains": list(training),
        "seasonal_domains": list(seasonal),
        "welfare_capacity_available": capacity,
    }


def person(pid, unit_id, deviations, unit, expected, *, scope=None, contact=True,
           status="ACTIVE", active=(), acute=(), suppressed=(), concern=False, note=""):
    return {
        "pid": pid,
        "unit_id": unit_id,
        "consent": {
            "scope": list(scope if scope is not None else ALL_SCOPE),
            "welfare_contact": contact,
            "status": status,
        },
        "unit": unit,
        "deviations": deviations,
        "active_interventions": list(active),
        "suppressed_drivers": list(suppressed),
        "acute_items": list(acute),
        "clinician_concern": concern,
        "expected": expected,
        "note": note,
    }


def cohort_escalate():
    u = unit_block(118)
    quiet = unit_block(118)
    people = [
        person(
            "pid-esc-0001", "UNIT-7RB",
            [dev("self_report", SUSTAINED, z_self=3.1),
             dev("leave", SUSTAINED, z_self=2.9),
             dev("duty_roster", SUSTAINED, z_self=2.6)],
            u, "ESCALATE",
            note="all four gates clear: T1 present, three domains, sustained, action available",
        ),
        person(
            "pid-esc-0002", "UNIT-7RB",
            [dev("leave", SUSTAINED), dev("duty_roster", SUSTAINED),
             dev("workload", SUSTAINED), dev("transfer", MONTH)],
            u, "ESCALATE",
            note="no self-report, but four corroborating service-record domains",
        ),
        person(
            "pid-esc-0003", "UNIT-7RB",
            [dev("self_report", BLIP, z_self=3.4)],
            quiet, "IMMEDIATE_ESCALATE", acute=("item_9",),
            note="acute item endorsed; bypasses persistence and evidence entirely",
        ),
    ]
    people += [
        person(f"pid-esc-{i:04d}", "UNIT-7RB", [dev("training", QUIET, z_self=1.1)],
               quiet, "MONITOR", note="background cohort: one weak domain, nothing sustained")
        for i in range(4, 12)
    ]
    return people


def cohort_monitor():
    deployed = unit_block(
        94,
        {"self_report": 0.45, "leave": 0.52, "duty_roster": 0.61, "workload": 0.58},
        unit_id="UNIT-3BN",
    )
    calm = unit_block(94, unit_id="UNIT-3BN")
    people = [
        person(
            "pid-mon-0001", "UNIT-3BN",
            [dev("self_report", SUSTAINED, z_self=3.0),
             dev("leave", SUSTAINED, z_self=2.9),
             dev("duty_roster", SUSTAINED, z_self=2.7)],
            deployed, "MONITOR",
            note="THE demo case: strong, sustained, three domains — but 45-61% of the "
                 "unit deviates the same way. Consistency 0.694 against 0.700. No name.",
        ),
        person(
            "pid-mon-0002", "UNIT-3BN",
            [dev("workload", SUSTAINED, z_self=3.6)],
            calm, "MONITOR",
            note="strong single-domain spike; evidence 0.246 — one domain never escalates",
        ),
        person(
            "pid-mon-0003", "UNIT-3BN",
            [dev("leave", BLIP), dev("duty_roster", BLIP), dev("self_report", BLIP)],
            calm, "MONITOR",
            note="broad and consented, but one bad week — persistence 0.332",
        ),
        person(
            "pid-mon-0004", "UNIT-3BN",
            [dev("leave", SUSTAINED, missing=0.34),
             dev("duty_roster", SUSTAINED, missing=0.34),
             dev("workload", SUSTAINED, missing=0.34)],
            calm, "MONITOR",
            note="a connector failed: 34% of records missing, data-gap confounder 0.80",
        ),
        person(
            "pid-mon-0005", "UNIT-3BN",
            [dev("leave", SUSTAINED), dev("duty_roster", SUSTAINED),
             dev("workload", SUSTAINED)],
            unit_block(94, leave=("leave",), training=("duty_roster",),
                       seasonal=("leave", "workload"), unit_id="UNIT-3BN"),
            "MONITOR",
            note="benign explanations stack: sanctioned leave AND a prior-year seasonal "
                 "pattern on the same leave signal (0.60 + 0.45), a scheduled course on "
                 "the roster, seasonal on workload. Consistency 0.688. One confounder per "
                 "domain would NOT have been enough — three corroborating domains are "
                 "hard to defeat, which is the point.",
        ),
    ]
    people += [
        person(f"pid-mon-{i:04d}", "UNIT-3BN", [dev("biometric", QUIET, z_self=1.0)],
               calm, "NO_FLAG",
               note="background cohort: a lone opt-in biometric trend matches no welfare "
                    "action, so actionability vetoes and the cycle closes. A flag nobody "
                    "can act on is noise.")
        for i in range(6, 9)
    ]
    people += [
        person(f"pid-mon-{i:04d}", "UNIT-3BN", [dev("workload", QUIET, z_self=1.2)],
               calm, "MONITOR", note="background cohort: actionable domain, nothing sustained")
        for i in range(9, 12)
    ]
    return people


def cohort_noflag():
    u = unit_block(76, unit_id="UNIT-11BN")
    people = [
        person(
            "pid-nof-0001", "UNIT-11BN",
            [dev("leave", SUSTAINED), dev("duty_roster", SUSTAINED),
             dev("self_report", SUSTAINED)],
            u, "NO_FLAG", active=("WLF-LEAVE",),
            note="real, sustained deviation — already under an active leave-review "
                 "intervention. Re-flagging would be the fastest way to lose trust.",
        ),
        person(
            "pid-nof-0002", "UNIT-11BN",
            [dev("leave", SUSTAINED), dev("duty_roster", SUSTAINED),
             dev("workload", SUSTAINED)],
            u, "NO_FLAG", contact=False,
            note="consented to analysis but NOT to being approached. Analysed, never surfaced.",
        ),
        person(
            "pid-nof-0003", "UNIT-11BN",
            [dev("leave", SUSTAINED), dev("self_report", SUSTAINED)],
            u, "NO_FLAG", scope=[], status="REVOKED",
            note="revoked consent: no basis at all. Visible to the auditor and nobody else.",
        ),
        person(
            "pid-nof-0004", "UNIT-11BN",
            [dev("leave", SUSTAINED), dev("duty_roster", SUSTAINED),
             dev("workload", SUSTAINED)],
            u, "ESCALATE", scope=RECORDS_ONLY,
            note="partial consent — service records only, no self-assessment channel — "
                 "and it still escalates on breadth alone (evidence 0.738). Narrowing "
                 "consent changes what is analysed, not whether the system may work with "
                 "what remains.",
        ),
    ]
    people += [
        person(f"pid-nof-{i:04d}", "UNIT-11BN", [dev("transfer", QUIET, z_self=0.9)],
               u, "MONITOR", note="background cohort")
        for i in range(5, 12)
    ]
    return people


COHORTS = {
    "escalate": (cohort_escalate, "Multi-domain, sustained, T1 present, no confounder."),
    "monitor": (cohort_monitor, "Strong signal, defeated by confounders or breadth. No name."),
    "noflag": (cohort_noflag, "Deviation present, but no consent basis or no available action."),
}


def main() -> int:
    random.seed(SEED)
    OUT.mkdir(exist_ok=True)
    for name, (builder, description) in COHORTS.items():
        payload = {
            "cohort": name,
            "description": description,
            "as_of": "2026-09-05",
            "seed": SEED,
            "personnel": builder(),
        }
        path = OUT / f"cohort_{name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
        print(f"{path.relative_to(ROOT)}: {len(payload['personnel'])} personnel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
