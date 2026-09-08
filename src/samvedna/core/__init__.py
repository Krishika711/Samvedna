"""L3 — the decision domain. Pure, deterministic, unit-tested, no I/O.

Nothing in this package imports a database, a network client, a clock or a model.
It is the part a reviewing officer, an auditor or a judge will interrogate, so it
has to be testable in milliseconds, reproducible bit-for-bit, and readable as
arithmetic rather than as software.
"""
