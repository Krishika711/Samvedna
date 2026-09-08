"""The audit ledger: append-only, hash-chained, tamper-evident."""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from samvedna.disclosure.audit import GENESIS, Ledger, LedgerWriteFailed

AT = datetime(2026, 9, 5, 2, 0, tzinfo=UTC)


def seeded():
    ledger = Ledger()
    ledger.append(actor="system", action="run.started", purpose="nightly", at=AT)
    ledger.append(actor="system", action="verdict.recorded", subject_pid="pid-1",
                  unit_id="UNIT-01", purpose="welfare", detail={"decision": "MONITOR"}, at=AT)
    ledger.append(actor="welfare_officer:WO-12", action="disclosure.granted",
                  subject_pid="pid-2", unit_id="UNIT-01", purpose="welfare:contact", at=AT)
    return ledger


def test_the_first_entry_chains_to_genesis():
    assert seeded().entries()[0].prev_hash == GENESIS


def test_each_entry_chains_to_the_one_before_it():
    entries = seeded().entries()
    for previous, current in zip(entries, entries[1:], strict=False):
        assert current.prev_hash == previous.entry_hash


def test_a_clean_chain_verifies():
    assert seeded().verify() == (True, "chain verified")


def test_altering_an_entry_breaks_verification_and_names_the_break():
    ledger = seeded()
    ledger._entries[1] = dataclasses.replace(ledger._entries[1], purpose="administrative")
    ok, reason = ledger.verify()
    assert not ok
    assert "entry 1" in reason


def test_removing_an_entry_breaks_the_chain():
    ledger = seeded()
    del ledger._entries[1]
    assert not ledger.verify()[0]


def test_reordering_entries_breaks_the_chain():
    ledger = seeded()
    ledger._entries[1], ledger._entries[2] = ledger._entries[2], ledger._entries[1]
    assert not ledger.verify()[0]


def test_there_is_no_update_and_no_delete_on_the_ledger():
    ledger = Ledger()
    for forbidden in ("update", "delete", "remove", "edit", "amend", "purge"):
        assert not hasattr(ledger, forbidden), f"Ledger exposes {forbidden}()"


def test_a_failed_write_raises_so_the_caller_must_abort():
    ledger = Ledger()
    ledger.fail_next_write = True
    with pytest.raises(LedgerWriteFailed):
        ledger.append(actor="system", action="disclosure.granted", subject_pid="pid-1")
    assert len(ledger) == 0


def test_the_ledger_holds_pseudonyms_never_names():
    for entry in seeded().entries():
        assert not entry.subject_pid or entry.subject_pid.startswith("pid-")
        assert "actor" not in entry.detail


def test_entries_are_retrievable_by_pid_and_by_action():
    ledger = seeded()
    assert len(ledger.for_pid("pid-1")) == 1
    assert len(ledger.for_action("disclosure.granted")) == 1


def test_the_head_advances_with_every_append():
    ledger = Ledger()
    first = ledger.head
    ledger.append(actor="system", action="run.started")
    assert ledger.head != first
