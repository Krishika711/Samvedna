"""Temporal windows. Days, everywhere, with no unit ambiguity."""
from __future__ import annotations

# Feature windows (PART 7 stage 3).
WINDOWS_DAYS: tuple[int, ...] = (7, 30, 90, 180)
# The person's own baseline is the longest window; the unit cohort baseline is
# computed over the same window so the two z-scores are comparable.
BASELINE_WINDOW_DAYS = 180
# ...and it ENDS this many days before `as_of`, so the baseline is disjoint from
# every window being scored against it.
#
# Without the lag, a sustained deviation is partly absorbed into the baseline it
# is being measured against: a 60-day surge sits inside a trailing 180-day mean
# and lifts the very number it is supposed to deviate from. Measured on the
# synthetic force, an obvious unit-wide surge produced z_self = 0.83 against a
# 2.0 threshold — invisible. The lag is the longest scored window, so no day can
# be in both the baseline and the evidence.
BASELINE_LAG_DAYS = 90
# Windows the persistence gate scores over.
SHORT_WINDOW_DAYS = 7
# The window the persistence gate is anchored on, and the one `mindchange`
# solves when it computes how many further breaching days would close the gate.
PRIMARY_WINDOW_DAYS = 30
LONG_WINDOW_DAYS = 90
PERSISTENCE_WINDOWS_DAYS: tuple[int, ...] = (
    SHORT_WINDOW_DAYS,
    PRIMARY_WINDOW_DAYS,
    LONG_WINDOW_DAYS,
)

# Longest unbroken run of duty days that a roster can sustain before the
# pattern itself is the welfare concern, regardless of how predictable it is.
# Two weeks on with no break is a rotation problem even if it happens like
# clockwork.
SUSTAINABLE_RUN_DAYS = 14

# How long an accepted confounder annotation suppresses a driver (PART 8.7).
CONFOUNDER_ANNOTATION_DAYS = 90
# An intervention counts as "active" for this long unless closed earlier.
INTERVENTION_ACTIVE_DAYS = 45
# Pseudonymisation salt rotation (PART 8.10).
SALT_ROTATION_DAYS = 90
# How long the derived feature store retains rows before ageing out.
FEATURE_RETENTION_DAYS = 365
# Audit ledger retention. Ledger rows hold no content, only the fact of events.
LEDGER_RETENTION_DAYS = 2555  # seven years
