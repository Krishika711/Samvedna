"""Consent is to a specific text, in a specific language, at a specific version.

DPDP §6 requires that consent be informed, and "informed" is a claim about what
the person actually read. A consent record that says only *that* somebody agreed
cannot answer the question that matters when it is challenged: **agreed to what,
in what words?**

So a `ConsentReceipt` carries the locale, the version of the text in that locale,
and a hash of the exact strings shown. Three consequences follow, and each is a
policy this module enforces rather than documents:

**A translation that has not been reviewed cannot ground consent.** Machine-drafted
text is fine for showing a reviewer what needs checking; it is not fine as the
legal basis for processing somebody's psychological data. Outside pilot mode, a
`draft` locale is refused.

**When the text changes, consent goes stale rather than carrying over.** A person
who agreed to the September wording did not agree to the October wording, and
silently carrying the old agreement forward is the exact failure the version
field exists to prevent.

**The locale files are the single source of truth.** This module reads the same
JSON the app renders, so the version recorded in the ledger and the version on the
screen cannot drift apart.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from samvedna.config.weights import DomainName

__all__ = [
    "LocaleText",
    "ConsentReceipt",
    "ConsentTextUnavailable",
    "load_locales",
    "locale_text",
    "available_locales",
    "make_receipt",
    "DEFAULT_LOCALE_DIR",
]

DEFAULT_LOCALE_DIR = Path("web") / "i18n" / "locales"
ReviewStatus = Literal["source", "draft", "reviewed"]


class ConsentTextUnavailable(RuntimeError):
    """Raised rather than falling back to another language.

    Falling back is the harmful default: it renders a screen the person can only
    partly read while reporting success, and nothing records that it happened.
    """


@dataclass(frozen=True, slots=True)
class LocaleText:
    """One language's consent text, and what is known about its provenance."""

    locale: str
    name: str
    english_name: str
    direction: Literal["ltr", "rtl"]
    text_version: str
    review_status: ReviewStatus
    reviewed_by: str
    reviewed_on: str
    content_hash: str

    @property
    def may_ground_consent(self) -> bool:
        """Only a source or reviewed translation may be the basis for consent."""
        return self.review_status in ("source", "reviewed")


@dataclass(frozen=True, slots=True)
class ConsentReceipt:
    """What the person read, in what language, and when.

    Kept alongside the consent state rather than inside it: `ConsentState` is what
    the decision layer reads, and the decision layer has no business knowing what
    language somebody speaks.
    """

    pid: str
    locale: str
    text_version: str
    content_hash: str
    review_status: ReviewStatus
    scope: frozenset[DomainName]
    welfare_contact: bool
    granted_at: datetime

    def is_current(self, current: LocaleText) -> bool:
        """False once the text changes — the person must be asked again."""
        return (
            self.text_version == current.text_version
            and self.content_hash == current.content_hash
        )

    def to_ledger_detail(self) -> dict[str, str | bool]:
        """What the ledger records. The locale and version, never the text."""
        return {
            "locale": self.locale,
            "text_version": self.text_version,
            "content_hash": self.content_hash[:16],
            "review_status": self.review_status,
            "welfare_contact": self.welfare_contact,
            "domains": ",".join(sorted(self.scope)),
        }


def _hash_content(payload: dict) -> str:
    """A stable hash of the translated strings, ignoring the metadata block.

    Metadata is excluded on purpose: bumping a reviewer's name must not
    invalidate every consent given under text that did not change.
    """
    body = {k: v for k, v in payload.items() if k != "_meta"}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@lru_cache(maxsize=8)
def load_locales(directory: str = str(DEFAULT_LOCALE_DIR)) -> dict[str, LocaleText]:
    path = Path(directory)
    out: dict[str, LocaleText] = {}
    for file in sorted(path.glob("*.json")):
        payload = json.loads(file.read_text(encoding="utf-8"))
        meta = payload["_meta"]
        out[meta["locale"]] = LocaleText(
            locale=meta["locale"],
            name=meta["name"],
            english_name=meta["englishName"],
            direction=meta["direction"],
            text_version=meta["textVersion"],
            review_status=meta["reviewStatus"],
            reviewed_by=meta["reviewedBy"],
            reviewed_on=meta["reviewedOn"],
            content_hash=_hash_content(payload),
        )
    return out


def locale_text(locale: str, directory: str = str(DEFAULT_LOCALE_DIR)) -> LocaleText:
    locales = load_locales(directory)
    if locale not in locales:
        raise ConsentTextUnavailable(
            f"no consent text for locale '{locale}'. It is not offered, and the "
            f"system will not substitute another language."
        )
    return locales[locale]


def available_locales(
    directory: str = str(DEFAULT_LOCALE_DIR), *, for_consent: bool = False
) -> tuple[LocaleText, ...]:
    """Every locale, or only those that may ground consent."""
    everything = tuple(load_locales(directory).values())
    if not for_consent:
        return everything
    return tuple(t for t in everything if t.may_ground_consent)


def make_receipt(
    pid: str,
    locale: str,
    scope: frozenset[DomainName] | tuple[DomainName, ...],
    *,
    welfare_contact: bool,
    pilot_mode: bool = False,
    directory: str = str(DEFAULT_LOCALE_DIR),
    at: datetime | None = None,
) -> ConsentReceipt:
    """Build a receipt, or refuse.

    `pilot_mode` is the single escape hatch, and it exists because a pilot unit
    testing a draft translation is exactly how a draft becomes reviewed. It is
    off by default and a deployment that leaves it on is misconfigured.
    """
    text = locale_text(locale, directory)
    if not text.may_ground_consent and not pilot_mode:
        raise ConsentTextUnavailable(
            f"the {text.english_name} translation is marked '{text.review_status}' "
            f"and has not been checked by a native speaker. Consent cannot be "
            f"recorded against it. Offer a reviewed language instead."
        )
    return ConsentReceipt(
        pid=pid,
        locale=text.locale,
        text_version=text.text_version,
        content_hash=text.content_hash,
        review_status=text.review_status,
        scope=frozenset(scope),
        welfare_contact=welfare_contact,
        granted_at=at or datetime.now(UTC),
    )
