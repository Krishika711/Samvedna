"""Gate thresholds and detection cut-offs.

Every number a verdict depends on lives here or in `weights.py`. A verdict is
only reproducible if the configuration it was computed under is identifiable, so
`CONFIG_VERSION` is stamped on every run record and every ledger entry. Changing
any value in this package means bumping it (PART 8.9) — prior verdicts stay
reproducible against the version they were made under.
"""
from __future__ import annotations

CONFIG_VERSION = "2026.09.05-1"

# --- the four gates (PART 6) -------------------------------------------------
GATE_THRESHOLDS: dict[str, float] = {
    "evidence": 0.65,
    "consistency": 0.70,
    "persistence": 0.60,
    "actionability": 0.50,
}

# --- confounder masses (PART 6.3) --------------------------------------------
# Each rule contributes weight *against* the signal in the consistency gate.
CONFOUNDER_MASS: dict[str, float] = {
    "unit_op_tempo": 0.70,
    "planned_leave_cycle": 0.60,
    "scheduled_training": 0.50,
    "seasonal_roster": 0.45,
    "data_gap": 0.80,
}

CONFOUNDER_LABEL: dict[str, str] = {
    "unit_op_tempo": "unit-wide operational tempo",
    "planned_leave_cycle": "planned/sanctioned leave cycle",
    "scheduled_training": "scheduled training commitment",
    "seasonal_roster": "seasonal roster pattern",
    "data_gap": "data gap artefact",
}

# Fraction of the unit cohort that must deviate the same way before the pattern
# is a command workload problem rather than an individual welfare concern.
UNIT_OP_TEMPO_COHORT_FRACTION = 0.40
# Missing-record fraction in a window above which the window is an artefact.
DATA_GAP_MISSING_FRACTION = 0.20

# --- deviation detection (PART 7 stage 4) ------------------------------------
# |z| against the person's own 180-day baseline before a domain counts as
# deviating at all. Two, not three: this is a screening step feeding four gates,
# not a decision.
DEVIATION_Z_SELF = 2.0
# A domain also counts as deviating if it is extreme against the unit cohort.
DEVIATION_Z_UNIT = 2.0
# Daily breach test used by the persistence windows.
DAILY_BREACH_Z = 1.5

# --- privacy (PART 10) -------------------------------------------------------
K_ANONYMITY_MIN = 5
# Laplace scale for DP-noised aggregates, per released statistic.
DP_EPSILON_PER_QUERY = 0.5
# Budget for one unit, for one period.
#
# Sized to the statistics the system actually offers, which is not how it was
# first set. At 10.0 a single heat map — 24 squares, a count and a mean each —
# cost 24 epsilon and exhausted a whole period before the commander had finished
# looking at one screen. A budget smaller than one legitimate view is not a
# privacy control, it is an outage.
#
# 60.0 covers a full heat map, the scalar indices, and room to look again later
# in the day. Repeat views of the *same* question cost nothing — they are
# re-served from the release cache, because fresh noise on a repeated question is
# what an averaging attack needs. See `disclosure/dpcache.py`.
DP_TOTAL_BUDGET = 60.0

# --- safety override (PART 6.7) ----------------------------------------------
# Instrument items that route immediately, bypassing gates. Keyed by instrument.
# Triggered by the *instrument*, never by a model score.
ACUTE_ITEMS: dict[str, tuple[str, ...]] = {
    "PHQ9": ("item_9",),
    "GAD7": (),
    "MBI_GS9": (),
}
# Value above which an acute item fires. PHQ-9 item 9 is scored 0..3; > 0 is any
# endorsement at all, which is the clinically accepted trigger.
ACUTE_ITEM_MIN_VALUE = 0

# --- model drift (PART 9) ----------------------------------------------------
# Population Stability Index above which escalation is frozen system-wide.
DRIFT_PSI_FREEZE = 0.25
