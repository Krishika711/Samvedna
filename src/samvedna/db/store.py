"""Persistent, encrypted storage — the `Directory` that survives a restart.

The problem statement asks for "data anonymization and secure storage
mechanisms", and until now this system had the first and not the second: an
in-memory dict, correct for a REPLAY demonstration and useless as a deployment
answer. This module is the deployment answer.

What is stored where, and why it differs:

* **`identities`** — the pid-to-person mapping, the only real PII in the
  system. Sealed with AES-256-GCM, one blob per row, bound to its pid. Even
  with the database file, an attacker gets pseudonyms and ciphertext.
* **`ledger_entries`** — the hash chain, in the clear on purpose. An audit
  ledger nobody can read without a key is not an audit ledger; its integrity
  matters and its confidentiality does not, because it records *that* a
  disclosure happened rather than what was disclosed. Chain verification on
  load is what protects it.
* **`consent_records`** — pid, scope, text version, timestamp. Keyed by pid,
  so it holds no identifier. Note what is absent: there is no `withdrawn_at`
  column that a report could group by. A withdrawal deletes the grant and
  writes a ledger entry, which is readable only through
  `revocations_for_auditor`.

The engine is SQLAlchemy, so the same schema runs on SQLite for a portable
demonstration and on PostgreSQL/TimescaleDB in a data centre. The
feature-store tables are deliberately *not* here: they are the volume that
wants TimescaleDB's compression and continuous aggregates, and shipping a
half-tuned hypertable definition would be worse than shipping the seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import (
    Integer,
    LargeBinary,
    String,
    create_engine,
    delete,
    event,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from samvedna.db.crypto import CipherUnavailable, FieldCipher
from samvedna.db.keys import KeyProvider, KeyUnavailable, provider_from_settings
from samvedna.disclosure.reidentify import Identity

__all__ = ["InsecureConfiguration", "SecureStore", "open_store"]


class InsecureConfiguration(RuntimeError):
    """Refuses to hold PII under a configuration that cannot protect it."""


class Base(DeclarativeBase):
    pass


class IdentityRow(Base):
    """One person, sealed.

    `salt_epoch` is stored because a pid is only meaningful within the epoch it
    was minted in. A pid from a rotated-out epoch must fail to resolve rather
    than resolve to the wrong person, and without the epoch on the row there is
    no way to tell the two cases apart.
    """

    __tablename__ = "identities"

    pid: Mapped[str] = mapped_column(String(128), primary_key=True)
    salt_epoch: Mapped[str] = mapped_column(String(32), index=True)
    sealed: Mapped[bytes] = mapped_column(LargeBinary)
    created_on: Mapped[str] = mapped_column(String(10))


class LedgerRow(Base):
    """The hash chain, in the clear. Integrity, not confidentiality."""

    __tablename__ = "ledger_entries"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    subject_pid: Mapped[str] = mapped_column(String(128), default="", index=True)
    unit_id: Mapped[str] = mapped_column(String(32), default="")
    purpose: Mapped[str] = mapped_column(String(64), default="")
    detail_json: Mapped[str] = mapped_column(String(2048), default="{}")
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    entry_hash: Mapped[str] = mapped_column(String(64))


class ConsentRow(Base):
    """Keyed by pid, so it holds no identifier.

    There is no `withdrawn_at`. Withdrawal deletes the row — a nullable
    timestamp is a column a dashboard can count, and "3 withdrawals in B Coy
    this month" is exactly the report that makes withdrawal unsafe to use.
    """

    __tablename__ = "consent_records"

    pid: Mapped[str] = mapped_column(String(128), primary_key=True)
    scope_csv: Mapped[str] = mapped_column(String(512))
    welfare_contact: Mapped[int] = mapped_column(Integer, default=1)
    text_version: Mapped[str] = mapped_column(String(32), default="")
    locale: Mapped[str] = mapped_column(String(8), default="")
    recorded_at: Mapped[str] = mapped_column(String(32), default="")


@dataclass
class SecureStore:
    """An encrypted `Directory`, plus consent and ledger persistence."""

    url: str
    cipher: FieldCipher
    salt_epoch: str
    key_description: str

    def __post_init__(self) -> None:
        self._engine = create_engine(self.url, future=True)
        _harden_sqlite(self._engine)
        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------- directory --
    def enrol(self, pid: str, identity: Identity, *, on: date | None = None) -> None:
        sealed = self.cipher.encrypt_record(
            {
                "service_number": identity.service_number,
                "name": identity.name,
                "rank": identity.rank,
                "unit_id": identity.unit_id,
                "contact": identity.contact,
            },
            bound_to=pid,
        )
        with Session(self._engine) as session:
            session.merge(
                IdentityRow(
                    pid=pid,
                    salt_epoch=self.salt_epoch,
                    sealed=sealed,
                    created_on=(on or datetime.now(UTC).date()).isoformat(),
                )
            )
            session.commit()

    def resolve(self, pid: str) -> Identity | None:
        """Satisfies the `Directory` protocol. Returns None, never a guess."""
        with Session(self._engine) as session:
            row = session.get(IdentityRow, pid)
            if row is None:
                return None
            # A pid minted under a rotated-out salt epoch must not resolve. It
            # is not the same pid any more, and returning the row it happens to
            # collide with would disclose the wrong person.
            if row.salt_epoch != self.salt_epoch:
                return None
            fields = self.cipher.decrypt_record(row.sealed, bound_to=pid)
            return Identity(**fields)

    def enrolled(self) -> int:
        with Session(self._engine) as session:
            return session.scalar(select(func.count(IdentityRow.pid))) or 0

    # --------------------------------------------------------- retention --
    def purge_identities_before(self, cutoff: date) -> int:
        """Retention. Deletes rows outright rather than flagging them.

        A `deleted` flag is not deletion. The DPDP Act's erasure obligation is
        satisfied by the row being gone, and a soft-delete leaves the PII in
        the file for anybody who reads it with a different query.
        """
        with Session(self._engine) as session:
            result = session.execute(
                delete(IdentityRow).where(IdentityRow.created_on < cutoff.isoformat())
            )
            session.commit()
            removed = int(result.rowcount or 0)
        if removed:
            self._reclaim()
        return removed

    def purge_rotated_epochs(self) -> int:
        """Drop identities whose pid epoch is no longer current."""
        with Session(self._engine) as session:
            result = session.execute(
                delete(IdentityRow).where(IdentityRow.salt_epoch != self.salt_epoch)
            )
            session.commit()
            removed = int(result.rowcount or 0)
        if removed:
            self._reclaim()
        return removed

    def _reclaim(self) -> None:
        """Make a purge actually erase, rather than merely unlink.

        Three steps, and each one exists because the previous one was not
        enough — this was worked out by grepping a purged pid out of the raw
        files, twice.

        1. `secure_delete` (set at connect) zeroes the deleted row's bytes
           instead of leaving them in a page marked free.
        2. VACUUM rewrites the database without the freed pages, so nothing
           remains in the main file.
        3. **The write-ahead log still holds the frames.** WAL is a history of
           writes — the insert *and* the delete — so after step 2 the purged
           pid was still sitting in the `-wal` sidecar. Checkpointing with
           TRUNCATE folds the log into the main file and truncates it to zero
           length.

        Order matters: VACUUM writes its rebuild through the WAL, so the
        checkpoint has to come after it.

        Under the DPDP Act erasure has to mean erasure, and "the row is
        unlinked from the b-tree" is not that.
        """
        if not self.url.startswith("sqlite"):
            # PostgreSQL reclaims through autovacuum. A manual VACUUM FULL takes
            # an exclusive lock on a table a live system is reading, so this is
            # a DBA's scheduled job rather than something to trigger from a
            # welfare run.
            return
        with self._engine.connect() as conn:
            conn.exec_driver_sql("VACUUM")
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")

    # ----------------------------------------------------------- consent --
    def record_consent(
        self,
        pid: str,
        scope: tuple[str, ...],
        *,
        welfare_contact: bool = True,
        text_version: str = "",
        locale: str = "",
    ) -> None:
        with Session(self._engine) as session:
            session.merge(
                ConsentRow(
                    pid=pid,
                    scope_csv=",".join(sorted(scope)),
                    welfare_contact=1 if welfare_contact else 0,
                    text_version=text_version,
                    locale=locale,
                    recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
                )
            )
            session.commit()

    def consent_scope(self, pid: str) -> tuple[str, ...]:
        with Session(self._engine) as session:
            row = session.get(ConsentRow, pid)
            if row is None or not row.scope_csv:
                return ()
            return tuple(row.scope_csv.split(","))

    def withdraw(self, pid: str) -> bool:
        """Deletes the grant. The ledger entry is the caller's job."""
        with Session(self._engine) as session:
            row = session.get(ConsentRow, pid)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True


def open_store(
    settings,
    *,
    provider: KeyProvider | None = None,
    url: str | None = None,
) -> SecureStore:
    """Open the encrypted store, or refuse and say why.

    Every failure path here is a refusal. There is no mode in which this
    function returns a store that writes identities in the clear, because a
    system that degrades to plaintext under load or misconfiguration is worse
    than one that stops — the operator never finds out.
    """
    keys = provider or provider_from_settings(settings)
    mode = getattr(settings, "mode", "replay")

    # A development key provider must not be able to hold live personnel data,
    # however the rest of the configuration is set.
    if mode != "replay" and not keys.is_production_safe:
        raise InsecureConfiguration(
            f"mode={mode} with {keys.description}. Configure hsm_endpoint, or "
            f"encryption_keyfile pointing at a 0600 key outside the project tree."
        )

    try:
        material = keys.key()
    except KeyUnavailable as exc:
        raise InsecureConfiguration(f"no encryption key: {exc}") from exc

    try:
        cipher = FieldCipher(material)
    except CipherUnavailable as exc:
        raise InsecureConfiguration(str(exc)) from exc

    target = url or getattr(settings, "database_url", "sqlite:///./samvedna.db")
    # SQLAlchemy's sync engine cannot drive the aiosqlite dialect, and the
    # difference is a confusing traceback deep in the driver rather than here.
    target = target.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")

    return SecureStore(
        url=target,
        cipher=cipher,
        salt_epoch=_epoch_of(settings),
        key_description=keys.description,
    )


def _epoch_of(settings) -> str:
    """The salt epoch a pid was minted in, as a short label."""
    epoch = getattr(settings, "salt_epoch", None)
    if epoch:
        return str(epoch)
    # Derived rather than random, so restarting the process does not orphan
    # every identity already in the database.
    import hashlib

    salt = str(getattr(settings, "pseudonym_salt", "")).encode("utf-8")
    return hashlib.sha256(salt).hexdigest()[:16]

def _harden_sqlite(engine) -> None:
    """Pragmas that make SQLite safe enough to hold sealed PII.

    `secure_delete` is the one that matters and the one that caught a real bug
    here. SQLite's DELETE marks a row's pages as free and leaves the bytes
    exactly where they were, so a retention purge left the ciphertext — and the
    pid alongside it — sitting in the file. A test that grepped the raw
    database for a purged pid found it still there. Under the DPDP Act erasure
    has to mean erasure, and "the row is unlinked from the b-tree" is not that.

    `foreign_keys` is off by default in SQLite, which surprises everybody once.
    """
    if not engine.url.get_backend_name().startswith("sqlite"):
        return

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA secure_delete = ON")
            cursor.execute("PRAGMA foreign_keys = ON")
            # WAL keeps readers from blocking the nightly write, and the -wal
            # sidecar is covered by the same volume encryption as the database.
            cursor.execute("PRAGMA journal_mode = WAL")
        finally:
            cursor.close()
