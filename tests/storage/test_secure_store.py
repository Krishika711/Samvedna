"""Encrypted storage at rest, and every path that must refuse rather than degrade.

The problem statement asks for "data anonymization and secure storage
mechanisms". Anonymisation was there from the start; storage was an in-memory
dict, which is the right answer for a REPLAY demonstration and no answer at all
for a deployment.

What these tests defend is not the cipher — AES-GCM is not this project's to get
right — but the decisions around it, which are the ones that actually go wrong
in the field: where the key lives, what happens when it is missing, and whether
anything can talk the system into writing a name in the clear.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from samvedna.db.crypto import CipherUnavailable, FieldCipher
from samvedna.db.keys import (
    HsmKeyProvider,
    KeyfileProvider,
    KeyUnavailable,
    PassphraseProvider,
    _decode_key_material,
    generate_keyfile,
)
from samvedna.db.store import InsecureConfiguration, open_store
from samvedna.disclosure.reidentify import Identity

ARJUN = Identity("CAPF-000001", "Arjun Sharma", "CT", "UNIT-01", "unit exchange ext 4021")

def all_bytes_written(database_url: str) -> bytes:
    """Every byte SQLite has put on disk, main file and sidecars.

    Reading only the `.db` file is a trap. In WAL mode a fresh write lives in
    the `-wal` sidecar and has not reached the main file yet, so a scan of the
    `.db` alone finds no personal data for the most reassuring possible reason:
    there is no data there at all. That is a test that passes while proving
    nothing, and it nearly shipped.
    """
    base = Path(str(database_url).split("///")[-1])
    blob = b""
    for path in (base, Path(f"{base}-wal"), Path(f"{base}-shm")):
        if path.exists():
            blob += path.read_bytes()
    return blob




@dataclass
class Settings:
    mode: str = "replay"
    pseudonym_salt: str = "replay-salt-not-for-production"
    hsm_endpoint: str | None = None
    encryption_keyfile: str | None = None
    database_url: str = ""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'samvedna.db'}")


# ------------------------------------------------------ the actual claim --

def test_no_personal_data_appears_in_the_database_file(tmp_path, settings):
    """The claim is "encrypted at rest". This is what that has to mean.

    An operator with the database file must get pseudonyms and ciphertext. If
    any of these strings is greppable out of the file, the feature does not
    exist however much AES is in the call stack.
    """
    store = open_store(settings)
    store.enrol("pid-aaa", ARJUN)

    raw = all_bytes_written(settings.database_url)

    for secret in (b"Arjun", b"Sharma", b"CAPF-000001", b"ext 4021", b"CT"):
        assert secret not in raw, f"{secret!r} is readable in the database file"
    # The pid is not PII — it is an HMAC under a rotating salt — and it has to
    # be in the clear to be a primary key. Asserting it is *present* is what
    # stops this test passing trivially on a file the row never reached.
    assert b"pid-aaa" in raw, "nothing was written — the scan above proved nothing"


def test_roundtrip_returns_the_identity_unchanged(settings):
    store = open_store(settings)
    store.enrol("pid-aaa", ARJUN)
    assert store.resolve("pid-aaa") == ARJUN


def test_an_unknown_pid_returns_none_rather_than_guessing(settings):
    store = open_store(settings)
    store.enrol("pid-aaa", ARJUN)
    assert store.resolve("pid-zzz") is None


# ------------------------------------------------- binding and tampering --

def test_ciphertext_cannot_be_moved_to_another_pid():
    """The attack this defends against needs no key at all.

    An attacker with write access to the database swaps one person's sealed
    blob onto another person's row. Without the pid as additional authenticated
    data, GCM decrypts it happily — the plaintext is valid, it is simply
    attached to the wrong human being, and the system discloses the wrong name
    to a welfare officer.
    """
    cipher = FieldCipher(os.urandom(32))
    sealed = cipher.encrypt_record({"name": "Arjun Sharma"}, bound_to="pid-aaa")

    assert cipher.decrypt_record(sealed, bound_to="pid-aaa") == {"name": "Arjun Sharma"}
    with pytest.raises(InvalidTag):
        cipher.decrypt_record(sealed, bound_to="pid-bbb")


def test_tampered_ciphertext_is_refused_not_partially_read():
    cipher = FieldCipher(os.urandom(32))
    sealed = bytearray(cipher.encrypt("Arjun Sharma", bound_to="pid-aaa"))
    sealed[20] ^= 0x01

    with pytest.raises(InvalidTag):
        cipher.decrypt(bytes(sealed), bound_to="pid-aaa")


def test_the_same_name_encrypts_differently_every_time():
    """A deterministic ciphertext would let an attacker match equal names.

    Two rows with identical ciphertext tell you two people share a name, or a
    unit, or a contact number — without any key. A fresh random nonce per
    encryption is what prevents that.
    """
    cipher = FieldCipher(os.urandom(32))
    a = cipher.encrypt("Arjun Sharma", bound_to="pid-aaa")
    b = cipher.encrypt("Arjun Sharma", bound_to="pid-aaa")
    assert a != b


def test_a_short_key_is_refused():
    with pytest.raises(CipherUnavailable, match="need 32"):
        FieldCipher(os.urandom(16))


# --------------------------------------------------------- key custody --

def test_a_keyfile_inside_the_project_tree_is_refused(tmp_path):
    """An in-tree key gets committed, and then emailed inside the archive.

    This project's whole transfer story is a zip file sent by email. A key in
    the tree travels with it, which turns encryption at rest into theatre.
    """
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    keyfile = generate_keyfile(root / "config" / "dek.key")

    with pytest.raises(KeyUnavailable, match="inside the project tree"):
        KeyfileProvider(keyfile, project_root=root).key()


def test_a_world_readable_keyfile_is_refused(tmp_path):
    keyfile = generate_keyfile(tmp_path / "dek.key")
    assert KeyfileProvider(keyfile, project_root=tmp_path / "elsewhere").key()

    os.chmod(keyfile, 0o644)
    with pytest.raises(KeyUnavailable, match="must be 0600"):
        KeyfileProvider(keyfile, project_root=tmp_path / "elsewhere").key()


def test_an_all_zero_keyfile_is_refused(tmp_path):
    """What a truncated or partially-written keyfile looks like.

    AES will encrypt under a zero key without complaint, and the result looks
    exactly as encrypted as anything else.
    """
    keyfile = tmp_path / "dek.key"
    keyfile.write_bytes(bytes(32))
    os.chmod(keyfile, 0o600)

    with pytest.raises(KeyUnavailable, match="all zeroes"):
        KeyfileProvider(keyfile, project_root=tmp_path / "elsewhere").key()


def test_generated_keyfiles_are_0600_and_32_bytes(tmp_path):
    keyfile = generate_keyfile(tmp_path / "dek.key")
    assert len(keyfile.read_bytes()) == 32
    assert (keyfile.stat().st_mode & 0o777) == 0o600


def test_the_hsm_provider_refuses_rather_than_faking_it():
    """A stub that returned a local key while calling itself an HSM provider
    would be the most dangerous class in this codebase."""
    with pytest.raises(KeyUnavailable, match="seam, not an implementation"):
        HsmKeyProvider("pkcs11://slot0").key()


def test_a_short_passphrase_salt_is_refused():
    with pytest.raises(KeyUnavailable, match="at least 16 bytes"):
        PassphraseProvider("a-long-enough-passphrase", b"tooshort")


# ------------------------------------------------------- fail closed --

def test_live_mode_refuses_a_development_key_provider(settings):
    """The single most important test in this file.

    There must be no configuration in which live personnel data is held under a
    passphrase-derived key. The check is in `open_store` as well as in
    `provider_from_settings`, because two checks on the path that decides
    whether PII is protected is the right number.
    """
    settings.mode = "live"
    with pytest.raises(InsecureConfiguration, match="NOT production safe"):
        open_store(settings)


def test_live_mode_accepts_a_proper_keyfile(tmp_path, settings):
    keyfile = generate_keyfile(tmp_path / "outside" / "dek.key")
    settings.mode = "live"
    store = open_store(
        settings, provider=KeyfileProvider(keyfile, project_root=tmp_path / "project")
    )
    store.enrol("pid-aaa", ARJUN)
    assert store.resolve("pid-aaa") == ARJUN


def test_a_missing_key_refuses_and_never_stores_plaintext(settings):
    with pytest.raises(InsecureConfiguration, match="no encryption key"):
        open_store(settings, provider=KeyfileProvider("/nonexistent/dek.key"))


# ---------------------------------------------------- epochs and retention --

def test_a_pid_from_a_rotated_out_salt_epoch_does_not_resolve(settings):
    """A rotated pid is not the same pid. Resolving it discloses a stranger."""
    store = open_store(settings)
    store.enrol("pid-aaa", ARJUN)
    assert store.resolve("pid-aaa") == ARJUN

    rotated = Settings(
        mode=settings.mode,
        pseudonym_salt="a-new-epoch-salt",
        database_url=settings.database_url,
    )
    after = open_store(rotated)
    assert after.resolve("pid-aaa") is None, "a stale-epoch pid resolved to a person"


def test_purging_rotated_epochs_deletes_the_rows(settings):
    store = open_store(settings)
    store.enrol("pid-aaa", ARJUN)

    rotated = Settings(
        pseudonym_salt="a-new-epoch-salt", database_url=settings.database_url
    )
    after = open_store(rotated)
    assert after.purge_rotated_epochs() == 1
    assert after.enrolled() == 0


def test_retention_deletes_rather_than_flagging(settings):
    """A `deleted` flag is not deletion.

    The DPDP Act's erasure obligation is satisfied by the row being gone. A
    soft delete leaves the ciphertext in the file, and leaves it decryptable by
    anybody holding the key and a different query.
    """
    store = open_store(settings)
    store.enrol("pid-old", ARJUN, on=date(2020, 1, 1))
    store.enrol("pid-new", ARJUN, on=date(2026, 9, 1))

    assert store.purge_identities_before(date(2024, 1, 1)) == 1
    assert store.resolve("pid-old") is None
    assert store.resolve("pid-new") is not None

    raw = all_bytes_written(settings.database_url)
    assert raw.count(b"pid-old") == 0, "a purged pid is still in the file"


# ------------------------------------------------------------- consent --

def test_withdrawal_leaves_no_column_a_report_could_group_by(settings):
    """There is deliberately no `withdrawn_at`.

    A nullable timestamp is a column a dashboard can count, and "3 withdrawals
    in B Coy this month" is exactly the report that makes withdrawal unsafe for
    the person exercising it.
    """
    from samvedna.db.store import ConsentRow

    columns = set(ConsentRow.__table__.columns.keys())
    for forbidden in ("withdrawn_at", "withdrawn", "revoked_at", "is_active"):
        assert forbidden not in columns, f"{forbidden} is groupable — remove it"

    store = open_store(settings)
    store.record_consent("pid-aaa", ("leave", "workload"), text_version="2026.09.05-1")
    assert store.consent_scope("pid-aaa") == ("leave", "workload")
    assert store.withdraw("pid-aaa") is True
    assert store.consent_scope("pid-aaa") == ()
    assert store.withdraw("pid-aaa") is False


# ------------------------------------------- key material, byte for byte --
#
# These exist because `KeyfileProvider.key()` used to be
# `path.read_bytes().strip()`, and that is wrong for binary in a way that only
# surfaced as a test failing roughly one run in twenty-one: `bytes.strip()`
# removes ASCII whitespace, and a random 32-byte key begins or ends with one of
# those six bytes about 4.7% of the time. In a deployment that is a key
# rotation with a 1-in-20 chance of refusing to start — or, with a looser
# length check, a silently *different* key encrypting data nothing could later
# decrypt.
#
# So the whitespace cases are pinned deterministically rather than left to luck.

def test_a_binary_key_whose_edges_are_whitespace_is_not_stripped():
    """The exact bug. Both edges are whitespace bytes on purpose."""
    key = b"\n" + bytes(range(1, 31)) + b" "
    assert len(key) == 32

    decoded = _decode_key_material(key)

    assert decoded == key, "whitespace bytes were stripped out of a binary key"
    assert len(decoded) == 32


@pytest.mark.parametrize("edge", [b" ", b"\t", b"\n", b"\r", b"\x0b", b"\x0c"])
def test_every_ascii_whitespace_byte_survives_at_both_edges(edge):
    """All six bytes `bytes.strip()` would have eaten."""
    key = edge + bytes(range(1, 31)) + edge
    assert _decode_key_material(key) == key


def test_a_generated_keyfile_always_round_trips(tmp_path):
    """Two hundred real generated keys, none rejected and none altered.

    Two hundred rather than five: at a 4.7% failure rate the old code would
    have been caught by this with probability greater than 99.99%, which is the
    difference between a regression test and a coin toss.
    """
    for i in range(200):
        keyfile = generate_keyfile(tmp_path / f"k{i}.key")
        expected = keyfile.read_bytes()
        got = KeyfileProvider(keyfile, project_root=tmp_path / "project").key()
        assert got == expected, f"key {i} was altered on read"
        assert len(got) == 32


def test_hex_and_base64_keyfiles_are_accepted():
    """How an operator who had to paste a key into a ticket will have stored it."""
    import base64

    key = bytes(range(32))
    assert _decode_key_material(key.hex().encode()) == key
    assert _decode_key_material(key.hex().upper().encode() + b"\n") == key
    assert _decode_key_material(base64.b64encode(key)) == key
    assert _decode_key_material(base64.b64encode(key) + b"\n") == key


def test_a_wrong_length_keyfile_is_refused_with_its_length():
    """A truncated file and the wrong file look identical. Refuse, don't guess."""
    with pytest.raises(KeyUnavailable, match="holds 5 bytes"):
        _decode_key_material(b"short")
    with pytest.raises(KeyUnavailable, match="expected 32 raw bytes"):
        _decode_key_material(bytes(31))
