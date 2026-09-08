"""personnel_id -> pid. HMAC under a rotating salt held in the HSM.

This is the single most important line of defence in the system, and it runs at
ingest — before features, before models, before anything that could log. PART 1
constraint 6 says no identifier reaches the model layer; the way to be sure of
that is for the model layer never to have been handed one.

Three properties, each tested:

* **Deterministic within a salt epoch.** The same service number maps to the same
  pid all night, or the nightly run cannot join a person's own records together.
* **Not reversible.** HMAC-SHA256, not a hash of the number alone — an unsalted
  digest of a six-digit service number is a rainbow table, not a pseudonym.
* **Rotating.** Old salts are destroyed on schedule, which caps how far back a
  compromised salt can re-identify.

The salt lives in an HSM in production. In REPLAY it is a local secret, and the
arithmetic is identical — the difference is where the key is kept, not what is
computed, so the offline path exercises the real code.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, timedelta

from samvedna.config.windows import SALT_ROTATION_DAYS

__all__ = ["Pseudonymiser", "SaltEpoch", "epoch_for"]

# A pid is a truncated HMAC. 128 bits is far beyond collision risk for a force of
# ten lakh, and a shorter token is one an officer can read aloud over a radio
# without transcription errors.
PID_HEX_CHARS = 32
EPOCH_ZERO = date(2026, 1, 1)


@dataclass(frozen=True, slots=True)
class SaltEpoch:
    """Which rotation period a pid belongs to.

    Carried alongside the pid because re-identification (L5) has to know which
    salt to reach for, and because a pid from an expired epoch must fail to
    resolve rather than silently resolving to the wrong person.
    """

    index: int
    starts_on: date
    ends_on: date

    @property
    def label(self) -> str:
        return f"E{self.index:04d}"


def epoch_for(day: date) -> SaltEpoch:
    index = (day - EPOCH_ZERO).days // SALT_ROTATION_DAYS
    start = EPOCH_ZERO + timedelta(days=index * SALT_ROTATION_DAYS)
    return SaltEpoch(index, start, start + timedelta(days=SALT_ROTATION_DAYS - 1))


class Pseudonymiser:
    """Turns a service number into a pid. Holds the salt; nothing else may.

    `secret` is an HSM handle in production. The class never logs it, never
    returns it, and never writes it into a record — including in an exception
    message, which is the usual way a secret escapes.
    """

    __slots__ = ("_secret", "_epoch")

    def __init__(self, secret: str, *, on: date | None = None) -> None:
        if not secret:
            raise ValueError("pseudonymisation salt is empty; refusing to run")
        self._secret = secret.encode("utf-8")
        self._epoch = epoch_for(on or date.today())

    @property
    def epoch(self) -> SaltEpoch:
        return self._epoch

    def pid(self, service_number: str) -> str:
        """The pseudonym. Deterministic within the epoch, one-way outside it."""
        message = f"{self._epoch.label}:{service_number}".encode()
        digest = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        return digest[:PID_HEX_CHARS]

    def verify(self, service_number: str, pid: str) -> bool:
        """Constant-time check, for L5 re-identification only."""
        return hmac.compare_digest(self.pid(service_number), pid)

    def __repr__(self) -> str:  # pragma: no cover - defensive
        return f"Pseudonymiser(epoch={self._epoch.label})"
