"""What a person did, kept so a restart does not undo it.

REPLAY holds the whole run in memory, which is right — no demonstration may
depend on live service-record access — and it means that everything a person
does *during* the day is lost when the process stops. Consent granted at 11:00,
a questionnaire completed at 11:05, a voice sitting at 11:10: all gone, and the
welfare officer's queue back to whatever the 02:00 batch produced. For a
demonstration that is merely annoying. For a pilot it would be unacceptable.

This journal fixes that, and the shape of the fix is the important part.

**It stores inputs, never derived verdicts.** A recorded `assessment.submitted`
event holds the score and the acute flag; it does not hold "this person was
escalated". On startup the events are replayed through the same gates the
nightly run used, so a verdict is always recomputed against the *current*
config version. Storing the verdict would mean a threshold change in
`config/` silently failed to apply to anybody who had already been decided —
the exact class of bug that makes a governance-approved threshold meaningless.

**It is append-only, and it stores the minimum.** An assessment writes a total
and whether an acute item fired. It does not write the nine item answers: an
officer may never see raw psychometric responses, the ledger does not hold
them, and neither does this. A voice sitting writes the six measured features
and the readings — never audio, never the transcript, which the sitting is
built to destroy.

**Everything is sealed.** A score is health data. Payloads are encrypted with
the same AES-256-GCM and the same key custody as the identity directory, bound
to the pid, so a stolen database file yields pseudonyms and ciphertext. See
`db/crypto.py` for why the binding matters.

**It degrades to nothing.** If the `secure` extra is absent, or no key is
available, `open_journal` returns None and the system runs exactly as it did
before — in memory, losing state on restart. Persistence is a feature to have,
not a dependency to fail on; a welfare run must not stop because a database is
unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Integer, LargeBinary, String, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from samvedna.db.crypto import CipherUnavailable, FieldCipher
from samvedna.db.keys import KeyProvider, KeyUnavailable, provider_from_settings
from samvedna.db.store import _harden_sqlite

__all__ = ["EventKind", "Journal", "JournalEvent", "open_journal"]

EventKind = Literal[
    "consent.granted",
    "consent.withdrawn",
    "assessment.submitted",
    "voice.sitting",
]


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    """One thing a person did.

    `kind` and `pid` are in the clear — a pid is an HMAC under a rotating salt,
    and the kind is needed to replay in the right order without decrypting
    everything first. The payload, which is the health data, is sealed.
    """

    __tablename__ = "journal"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    pid: Mapped[str] = mapped_column(String(128), index=True)
    salt_epoch: Mapped[str] = mapped_column(String(32), index=True)
    sealed: Mapped[bytes] = mapped_column(LargeBinary)


@dataclass(frozen=True, slots=True)
class JournalEvent:
    seq: int
    at: datetime
    kind: EventKind
    pid: str
    payload: dict


@dataclass
class Journal:
    """Append-only, replayable, sealed."""

    url: str
    cipher: FieldCipher
    salt_epoch: str

    def __post_init__(self) -> None:
        self._engine = create_engine(self.url, future=True)
        _harden_sqlite(self._engine)
        Base.metadata.create_all(self._engine)

    def record(self, kind: EventKind, pid: str, payload: dict) -> int:
        sealed = self.cipher.encrypt_record(
            {k: json.dumps(v) for k, v in payload.items()}, bound_to=pid
        )
        with Session(self._engine) as session:
            row = EventRow(
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                kind=kind,
                pid=pid,
                salt_epoch=self.salt_epoch,
                sealed=sealed,
            )
            session.add(row)
            session.commit()
            return row.seq

    def replay(self) -> tuple[JournalEvent, ...]:
        """Every event, oldest first, for the current salt epoch only.

        A pid minted under a rotated-out epoch is not the same pid, so replaying
        its events would attach somebody's questionnaire to a stranger. Those
        rows are skipped rather than deleted — `purge_rotated_epochs` is a
        deliberate act, not a side effect of starting up.
        """
        out: list[JournalEvent] = []
        with Session(self._engine) as session:
            rows = session.scalars(
                select(EventRow)
                .where(EventRow.salt_epoch == self.salt_epoch)
                .order_by(EventRow.seq)
            ).all()
            for row in rows:
                try:
                    fields = self.cipher.decrypt_record(row.sealed, bound_to=row.pid)
                except Exception:
                    # A row that will not open is a row that was tampered with,
                    # moved, or written under another key. Skipping it is right;
                    # guessing at its contents is not. It stays on disk for an
                    # auditor to find.
                    continue
                out.append(
                    JournalEvent(
                        seq=row.seq,
                        at=datetime.fromisoformat(row.at),
                        kind=row.kind,  # type: ignore[arg-type]
                        pid=row.pid,
                        payload={k: json.loads(v) for k, v in fields.items()},
                    )
                )
        return tuple(out)

    def __len__(self) -> int:
        with Session(self._engine) as session:
            return len(session.scalars(select(EventRow.seq)).all())

    # `__len__` without `__bool__` is how an empty ledger once became falsy and
    # silently swallowed nine audit entries. Same shape, same fix.
    def __bool__(self) -> bool:
        return True

    def purge_rotated_epochs(self) -> int:
        with Session(self._engine) as session:
            result = session.execute(
                delete(EventRow).where(EventRow.salt_epoch != self.salt_epoch)
            )
            session.commit()
            return int(result.rowcount or 0)

    def forget(self, pid: str) -> int:
        """Erase one person's events outright.

        The DPDP Act's erasure obligation reaches this table too. A withdrawal
        that leaves a sealed questionnaire score on disk has not erased
        anything — it has changed a flag.
        """
        with Session(self._engine) as session:
            result = session.execute(delete(EventRow).where(EventRow.pid == pid))
            session.commit()
            removed = int(result.rowcount or 0)
        if removed and self.url.startswith("sqlite"):
            with self._engine.connect() as conn:
                conn.exec_driver_sql("VACUUM")
                conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        return removed


def open_journal(settings, *, provider: KeyProvider | None = None) -> Journal | None:
    """Open the journal, or return None and let the system run in memory.

    Returning None rather than raising is the whole contract. A missing crypto
    library or an unavailable key means "no persistence", not "no welfare run" —
    the alternative is a system that refuses to assess anybody because a
    database was down, which inverts what it is for.

    What it will *not* do is fall back to storing scores in the clear. There is
    no such path.
    """
    if not getattr(settings, "persist_state", True):
        return None
    try:
        keys = provider or provider_from_settings(settings)
        material = keys.key()
        cipher = FieldCipher(material)
    except (KeyUnavailable, CipherUnavailable):
        return None

    url = str(getattr(settings, "database_url", "sqlite:///./samvedna.db"))
    url = url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")

    import hashlib

    salt = str(getattr(settings, "pseudonym_salt", "")).encode("utf-8")
    epoch = hashlib.sha256(salt).hexdigest()[:16]
    try:
        return Journal(url=url, cipher=cipher, salt_epoch=epoch)
    except Exception:
        # A database that cannot be opened is not a reason to stop.
        return None
