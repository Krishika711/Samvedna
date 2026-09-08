"""Field-level AES-256-GCM, bound to the row it belongs to.

Two decisions in here are the ones worth arguing about.

**Only the identity directory is encrypted at field level.** Everything
downstream of pseudonymisation is keyed by pid, and a pid is an HMAC of a
service number under a rotating salt — it is not PII, and encrypting a table
full of pids and z-scores would cost every read while protecting nothing an
attacker could use. What actually needs field-level protection is the one table
that maps a pid back to a person, and that table is small. Volume encryption
covers the rest, and saying so plainly is better than a claim of
"everything encrypted" that means "everything, badly".

**The pid is the AAD.** Additional authenticated data binds a ciphertext to its
row, so an attacker with write access to the database cannot take the
ciphertext for one person and move it onto another person's pid to make the
system disclose the wrong name. Without AAD, GCM would happily decrypt it —
the plaintext is valid, it is just attached to the wrong human being. That
attack needs no key at all, which is what makes it worth ten lines of code.

GCM rather than CBC: it authenticates. A CBC ciphertext can be modified by an
attacker without the key in ways that produce a different valid plaintext, and
the application cannot tell.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

__all__ = ["CipherUnavailable", "FieldCipher", "NONCE_BYTES"]

# 96 bits, the size GCM is specified for. A random nonce per encryption, never
# a counter: a counter that restarts (a restored backup, a redeployed pod)
# reuses a nonce under the same key, and nonce reuse in GCM does not merely
# leak — it leaks the authentication key.
NONCE_BYTES = 12

# Bumped if the wire format ever changes, so an old row is recognisably old
# rather than silently misparsed.
FORMAT_VERSION = 1


class CipherUnavailable(RuntimeError):
    """No cipher backend. There is no plaintext fallback, deliberately."""


@dataclass(frozen=True, slots=True)
class FieldCipher:
    """Encrypts and decrypts one logical field, bound to a row key."""

    key: bytes

    def __post_init__(self) -> None:
        if len(self.key) != 32:
            raise CipherUnavailable(f"key is {len(self.key)} bytes, need 32 for AES-256")

    @staticmethod
    def _aesgcm(key: bytes):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise CipherUnavailable(
                "AES-GCM needs the `secure` extra: uv sync --extra secure. "
                "There is no unencrypted fallback for identity storage."
            ) from exc
        return AESGCM(key)

    def encrypt(self, plaintext: str, *, bound_to: str) -> bytes:
        """`bound_to` is the pid. Ciphertext is useless on any other row."""
        aead = self._aesgcm(self.key)
        nonce = os.urandom(NONCE_BYTES)
        sealed = aead.encrypt(
            nonce, plaintext.encode("utf-8"), bound_to.encode("utf-8")
        )
        return bytes([FORMAT_VERSION]) + nonce + sealed

    def decrypt(self, blob: bytes, *, bound_to: str) -> str:
        if not blob or blob[0] != FORMAT_VERSION:
            raise CipherUnavailable(
                f"unrecognised ciphertext format {blob[:1]!r}; expected version "
                f"{FORMAT_VERSION}"
            )
        aead = self._aesgcm(self.key)
        nonce = blob[1 : 1 + NONCE_BYTES]
        body = blob[1 + NONCE_BYTES :]
        # An InvalidTag here means the row was tampered with, moved to another
        # pid, or encrypted under a different key. All three are the same
        # answer: refuse. Never return a partial or best-effort plaintext.
        opened = aead.decrypt(nonce, body, bound_to.encode("utf-8"))
        return opened.decode("utf-8")

    def encrypt_record(self, fields: dict[str, str], *, bound_to: str) -> bytes:
        """The whole identity as one sealed blob rather than a column each.

        One blob, not five. Per-column ciphertexts leak the shape of the record
        — an attacker learns which people have a listed contact number and
        which do not from the null columns alone, and lengths leak more.
        """
        canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
        return self.encrypt(canonical, bound_to=bound_to)

    def decrypt_record(self, blob: bytes, *, bound_to: str) -> dict[str, str]:
        return json.loads(self.decrypt(blob, bound_to=bound_to))
