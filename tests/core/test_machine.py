"""Illegal state transitions raise. A warning in a nightly batch is unread."""
from __future__ import annotations

import pytest

from samvedna.core.machine import LEGAL, IllegalTransition, assert_transition


def test_the_happy_path_is_legal():
    path = ["OBSERVED", "DEVIATING", "SCORED", "REVIEWED", "GATED", "ESCALATED",
            "CONTACTED", "CLOSED"]
    for a, b in zip(path, path[1:], strict=False):
        assert_transition(a, b)


def test_nothing_reaches_escalated_without_passing_through_gated():
    for state in LEGAL:
        if state in ("GATED", "MONITORED"):
            continue
        assert "ESCALATED" not in LEGAL[state], f"{state} can reach ESCALATED directly"


def test_scoring_cannot_skip_review():
    with pytest.raises(IllegalTransition):
        assert_transition("SCORED", "GATED")


def test_a_closed_case_is_terminal():
    assert LEGAL["CLOSED"] == frozenset()
    with pytest.raises(IllegalTransition):
        assert_transition("CLOSED", "OBSERVED")


def test_a_monitored_pid_re_enters_observation_next_cycle():
    assert_transition("MONITORED", "OBSERVED")


def test_a_monitored_case_can_be_manually_escalated_by_an_officer():
    assert_transition("MONITORED", "ESCALATED")
