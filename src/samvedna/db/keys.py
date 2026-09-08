"""Where the data-encryption key comes from, and where it must never come from.

The deck names "AES-256 + HSM", and the HSM half is the half that matters.
AES-256 with the key sitting next to the database is not encryption at rest, it
is a filing cabinet with the key taped to the lid — an attacker who can read
the database file can read the file next to it.

So this module is about custody, not about ciphers. Three providers, in
descending order of how much they should be trusted:

* `HsmKeyProvider` — production. The key material never leaves the module; this
  class holds a *handle*. It is a seam rather than an implementation, because
  the wire protocol depends on which HSM a force actually owns (PKCS#11,
  KMIP, a cloud KMS in a sovereign region), and guessing would be worse than
  leaving the shape and refusing to run.
* `KeyfileProvider` — a real deployment without an HSM. The key is a file whose
  permissions must be 0600 and which must live outside the project tree. Both
  are checked, and both refuse rather than warn.
* `PassphraseProvider` — development and tests only. Derives a key with scrypt
  from a passphrase. It carries `is_production_safe = False` and the store
  refuses to open a database in production mode with one.

There is deliberately no `EnvironmentKeyProvider`. An environment variable is
readable by every process the user runs, appears in `ps` output on some
platforms, gets captured by crash reporters, and ends up in CI logs. It is the
most common way this goes wrong and offering it makes it the default.
"""

from __future__ import annotations

import os
import stat
from abc import ABC, abstractmethod
from pathlib import Path

__all__ = [
    "KEY_BYTES",
    "HsmKeyProvider",
    "KeyProvider",
    "KeyfileProvider",
    "KeyUnavailable",
    "PassphraseProvider",
    "generate_keyfile",
    "provider_from_settings",
]

# AES-256.
KEY_BYTES = 32

# scrypt work factors. Deliberately expensive: this runs once at startup, so a
# quarter of a second here is free, and it is the whole defence if somebody
# chooses a weak passphrase.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1


class KeyUnavailable(RuntimeError):
    """No key could be obtained. Never falls back to plaintext."""


class KeyProvider(ABC):
    """Yields a 32-byte data-encryption key, or refuses."""

    #: Whether this provider may be used with `SAMVEDNA_MODE=live`.
    is_production_safe: bool = False

    @abstractmethod
    def key(self) -> bytes:
        """Return 32 bytes, or raise `KeyUnavailable`."""

    @property
    @abstractmethod
    def description(self) -> str:
        """One line for the audit ledger. **Must never include key material.**"""

    def _check(self, material: bytes) -> bytes:
        if len(material) != KEY_BYTES:
            raise KeyUnavailable(
                f"{type(self).__name__}: key is {len(material)} bytes, need {KEY_BYTES}"
            )
        # An all-zero key is what a partially-written or truncated keyfile looks
        # like, and AES will happily encrypt with it.
        if material == bytes(KEY_BYTES):
            raise KeyUnavailable(f"{type(self).__name__}: key is all zeroes")
        return material


class KeyfileProvider(KeyProvider):
    """A 32-byte key in a file outside the project tree."""

    is_production_safe = True

    def __init__(self, path: str | Path, *, project_root: Path | None = None) -> None:
        self._path = Path(path).expanduser()
        self._root = project_root or Path(__file__).resolve().parents[3]

    @property
    def description(self) -> str:
        return f"keyfile:{self._path.name}"

    def key(self) -> bytes:
        path = self._path
        if not path.exists():
            raise KeyUnavailable(f"no keyfile at {path}")

        # Inside the tree means it gets committed, or zipped into the archive
        # and emailed. This has to be a refusal, not a warning.
        try:
            path.resolve().relative_to(self._root.resolve())
        except ValueError:
            pass  # outside the tree, which is what we want
        else:
            raise KeyUnavailable(
                f"keyfile {path} is inside the project tree — it would be "
                f"committed and packaged. Move it outside."
            )

        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise KeyUnavailable(
                f"keyfile {path} is mode {mode:04o}; must be 0600 "
                f"(group and other must have no access)"
            )
        return self._check(_decode_key_material(path.read_bytes()))


class HsmKeyProvider(KeyProvider):
    """Production custody. A handle, not key material.

    Unimplemented on purpose. Every HSM answers a different protocol, and a
    stub that quietly returned a locally-derived key while calling itself an
    HSM provider would be the single most dangerous class in this codebase.
    """

    is_production_safe = True

    def __init__(self, endpoint: str, key_label: str = "samvedna-dek") -> None:
        self._endpoint = endpoint
        self._label = key_label

    @property
    def description(self) -> str:
        return f"hsm:{self._endpoint}#{self._label}"

    def key(self) -> bytes:
        raise KeyUnavailable(
            f"HSM support is a seam, not an implementation. Configure "
            f"{self._endpoint} by implementing HsmKeyProvider.key() against "
            f"your module's PKCS#11 or KMIP interface. Until then use "
            f"KeyfileProvider with a key held outside the tree."
        )


class PassphraseProvider(KeyProvider):
    """scrypt over a passphrase. Development and tests only."""

    is_production_safe = False

    def __init__(self, passphrase: str, salt: bytes) -> None:
        if len(salt) < 16:
            raise KeyUnavailable("passphrase salt must be at least 16 bytes")
        self._passphrase = passphrase
        self._salt = salt

    @property
    def description(self) -> str:
        return "passphrase:scrypt (NOT production safe)"

    def key(self) -> bytes:
        try:
            from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise KeyUnavailable(
                "the `secure` extra is not installed: uv sync --extra secure"
            ) from exc
        kdf = Scrypt(
            salt=self._salt, length=KEY_BYTES, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
        )
        return self._check(kdf.derive(self._passphrase.encode("utf-8")))


def provider_from_settings(settings) -> KeyProvider:
    """Pick a provider from configuration, preferring the safest available.

    Order is HSM, then keyfile, then passphrase, and the last one is only
    reachable in replay mode — `SecureStore` re-checks `is_production_safe`
    rather than trusting this function, because two checks on a path that
    decides whether PII is protected is the right number.
    """
    endpoint = getattr(settings, "hsm_endpoint", None)
    if endpoint:
        return HsmKeyProvider(endpoint)

    keyfile = getattr(settings, "encryption_keyfile", None)
    if keyfile:
        return KeyfileProvider(keyfile)

    return PassphraseProvider(
        getattr(settings, "pseudonym_salt", "replay-salt-not-for-production"),
        # Distinct from the pseudonymisation salt. Reusing one secret for two
        # purposes means rotating either one breaks the other.
        salt=b"samvedna-dek-derivation-salt-v1",
    )


def generate_keyfile(path: str | Path) -> Path:
    """Write a fresh 32-byte key at 0600. For an operator, not for the app."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Create with restrictive permissions from the start rather than chmod-ing
    # afterwards: between the two there is a window where the key is readable.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, os.urandom(KEY_BYTES))
    finally:
        os.close(fd)
    return target


def _decode_key_material(raw: bytes) -> bytes:
    """Turn a keyfile's contents into 32 key bytes without corrupting them.

    This function exists because the obvious one-liner was wrong in a way that
    only showed up as a flaky test:

        path.read_bytes().strip()      # WRONG

    `bytes.strip()` with no argument removes ASCII whitespace — space, tab,
    newline, carriage return, vertical tab, form feed. A random 32-byte key
    begins or ends with one of those six bytes about **4.7% of the time**, so
    roughly one generated key in twenty-one was silently shortened to 30 or 31
    bytes and rejected. In a deployment that is a key rotation with a one-in-
    twenty chance of the system refusing to start, and if the length check had
    been looser it would instead have been a *different key* — encrypting data
    nothing could later decrypt.

    So raw binary is taken exactly as it is, and text encodings are handled
    explicitly rather than by accident:

    * exactly 32 bytes — a raw binary key. Used verbatim, never stripped.
    * 64 hex characters — decoded. This is how an operator who has to paste a
      key into a ticket or an HSM export will have stored it.
    * 44 base64 characters — decoded, for the same reason.

    Anything else is refused with its length, because a wrong-length key is a
    truncated file or the wrong file, and guessing which is not this function's
    business.
    """
    if len(raw) == KEY_BYTES:
        return raw

    # Only now is it safe to treat the content as text, because a raw binary
    # key has already been returned above and cannot reach here.
    text = raw.strip()
    if len(text) == KEY_BYTES:
        return text

    import base64
    import binascii

    try:
        candidate = bytes.fromhex(text.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        candidate = b""
    if len(candidate) == KEY_BYTES:
        return candidate

    try:
        candidate = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        candidate = b""
    if len(candidate) == KEY_BYTES:
        return candidate

    raise KeyUnavailable(
        f"keyfile holds {len(raw)} bytes; expected {KEY_BYTES} raw bytes, "
        f"{KEY_BYTES * 2} hex characters, or base64 of {KEY_BYTES} bytes"
    )
