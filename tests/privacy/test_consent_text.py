"""Consent is to a specific text, in a specific language, at a specific version.

DPDP §6 requires consent to be *informed*, and informed is a claim about what the
person actually read. These tests check the claim rather than the intention.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from samvedna.config.weights import ALL_DOMAINS
from samvedna.disclosure.audit import Ledger
from samvedna.disclosure.consent import ConsentRegistry
from samvedna.disclosure.consent_text import (
    ConsentTextUnavailable,
    available_locales,
    load_locales,
    locale_text,
    make_receipt,
)

ROOT = Path(__file__).resolve().parent.parent.parent
LOCALE_DIR = ROOT / "web" / "i18n" / "locales"
AT = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear_cache():
    load_locales.cache_clear()
    yield
    load_locales.cache_clear()


def locales():
    return load_locales(str(LOCALE_DIR))


# ------------------------------------------------------------ the locale set --
def test_every_locale_file_loads_with_complete_metadata():
    for code, text in locales().items():
        assert text.locale == code
        assert text.name and text.english_name
        assert text.direction in ("ltr", "rtl")
        assert text.text_version
        assert text.review_status in ("source", "draft", "reviewed")
        assert len(text.content_hash) == 64


def test_english_is_the_source_and_is_consent_capable():
    english = locale_text("en", str(LOCALE_DIR))
    assert english.review_status == "source"
    assert english.may_ground_consent


def test_every_language_names_itself_in_its_own_script():
    """A person scans for the shape of their own writing. A list reading
    'Hindi / Bengali / Tamil' in Latin asks them to read English to escape it."""
    for code, text in locales().items():
        if code == "en":
            continue
        assert text.name != text.english_name, f"{code} shows the English exonym"
        assert not text.name.isascii(), f"{code} name '{text.name}' is not in its script"


def test_at_least_one_right_to_left_language_is_supported():
    assert any(t.direction == "rtl" for t in locales().values())


def test_every_locale_shares_the_source_text_version():
    versions = {t.text_version for t in locales().values()}
    assert len(versions) == 1, f"locales disagree on the text version: {versions}"


def test_each_locale_has_a_distinct_content_hash():
    """Two locales with the same hash means one was copied and not translated."""
    hashes = [t.content_hash for t in locales().values()]
    assert len(set(hashes)) == len(hashes)


# ------------------------------------------------- refusing rather than falling back --
def test_an_unknown_locale_is_refused_not_substituted():
    with pytest.raises(ConsentTextUnavailable) as excinfo:
        locale_text("xx", str(LOCALE_DIR))
    assert "will not substitute another language" in str(excinfo.value)


def test_consent_is_refused_against_a_draft_translation():
    """Machine-drafted text is fine for a reviewer. It is not fine as the legal
    basis for processing somebody's psychological data."""
    with pytest.raises(ConsentTextUnavailable) as excinfo:
        make_receipt("p1", "hi", ALL_DOMAINS, welfare_contact=True,
                     directory=str(LOCALE_DIR), at=AT)
    assert "has not been checked by a native speaker" in str(excinfo.value)
    assert "Offer a reviewed language instead" in str(excinfo.value)


def test_pilot_mode_allows_a_draft_and_records_that_it_was_a_draft():
    receipt = make_receipt("p1", "hi", ALL_DOMAINS, welfare_contact=True,
                           pilot_mode=True, directory=str(LOCALE_DIR), at=AT)
    assert receipt.locale == "hi"
    assert receipt.review_status == "draft"
    assert receipt.to_ledger_detail()["review_status"] == "draft"


def test_only_reviewed_locales_are_offered_for_consent():
    everything = {t.locale for t in available_locales(str(LOCALE_DIR))}
    for_consent = {t.locale for t in available_locales(str(LOCALE_DIR), for_consent=True)}
    assert for_consent < everything
    assert "en" in for_consent


# ------------------------------------------------------------------ receipts --
def test_a_receipt_records_the_language_the_version_and_the_exact_text():
    receipt = make_receipt("p1", "en", ("leave", "duty_roster"),
                           welfare_contact=True, directory=str(LOCALE_DIR), at=AT)
    assert receipt.locale == "en"
    assert receipt.text_version == locale_text("en", str(LOCALE_DIR)).text_version
    assert receipt.content_hash == locale_text("en", str(LOCALE_DIR)).content_hash
    assert receipt.granted_at == AT


def test_the_ledger_detail_holds_the_version_never_the_text():
    receipt = make_receipt("p1", "en", ("leave",), welfare_contact=True,
                           directory=str(LOCALE_DIR), at=AT)
    detail = receipt.to_ledger_detail()
    assert detail["locale"] == "en"
    assert detail["text_version"]
    blob = str(detail)
    assert "It can see" not in blob, "the ledger must not carry the consent prose"
    assert len(detail["content_hash"]) == 16


def test_changing_the_text_makes_an_existing_consent_stale(tmp_path):
    """A person who agreed to the September wording did not agree to the October
    wording. Carrying it forward is what the version field exists to prevent."""
    import shutil

    shutil.copytree(LOCALE_DIR, tmp_path / "loc")
    receipt = make_receipt("p1", "en", ALL_DOMAINS, welfare_contact=True,
                           directory=str(tmp_path / "loc"), at=AT)
    load_locales.cache_clear()

    target = tmp_path / "loc" / "en.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["_meta"]["textVersion"] = "2026.12.01-1"
    payload["withdraw"]["body"] = "Reworded after a legal review."
    target.write_text(json.dumps(payload, ensure_ascii=False))
    load_locales.cache_clear()

    current = locale_text("en", str(tmp_path / "loc"))
    assert not receipt.is_current(current)


def test_a_metadata_only_change_does_not_invalidate_consent(tmp_path):
    """Bumping a reviewer's name must not invalidate every consent given under
    text that did not change."""
    import shutil

    shutil.copytree(LOCALE_DIR, tmp_path / "loc")
    receipt = make_receipt("p1", "en", ALL_DOMAINS, welfare_contact=True,
                           directory=str(tmp_path / "loc"), at=AT)
    load_locales.cache_clear()

    target = tmp_path / "loc" / "en.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["_meta"]["reviewedBy"] = "somebody else"
    target.write_text(json.dumps(payload, ensure_ascii=False))
    load_locales.cache_clear()

    assert receipt.content_hash == locale_text("en", str(tmp_path / "loc")).content_hash


# ----------------------------------------------------- the registry integration --
def test_enrolling_with_a_receipt_records_both():
    registry = ConsentRegistry()
    state, receipt = registry.enrol_with_receipt(
        "p1", ALL_DOMAINS, welfare_contact=True, locale="en",
        locale_dir=str(LOCALE_DIR), at=AT,
    )
    assert state.status == "ACTIVE"
    assert registry.receipt_for("p1") == receipt


def test_a_draft_locale_is_refused_by_the_registry_too():
    registry = ConsentRegistry()
    with pytest.raises(ConsentTextUnavailable):
        registry.enrol_with_receipt(
            "p1", ALL_DOMAINS, welfare_contact=True, locale="ur",
            locale_dir=str(LOCALE_DIR), at=AT,
        )
    assert registry.state_for("p1") is None, "a refused consent must enrol nobody"


def test_current_consent_does_not_need_re_asking():
    registry = ConsentRegistry()
    registry.enrol_with_receipt("p1", ALL_DOMAINS, welfare_contact=True,
                                locale="en", locale_dir=str(LOCALE_DIR), at=AT)
    stale, why = registry.needs_reconsent("p1", locale_dir=str(LOCALE_DIR))
    assert not stale
    assert "matches the current text" in why


def test_consent_without_a_receipt_needs_re_asking():
    """Legacy consent, granted before receipts existed, cannot answer 'to what?'."""
    registry = ConsentRegistry()
    registry.enrol("p1", ALL_DOMAINS, welfare_contact=True, at=AT)
    stale, why = registry.needs_reconsent("p1", locale_dir=str(LOCALE_DIR))
    assert stale
    assert "no receipt" in why


def test_an_unenrolled_person_is_not_asked_to_re_consent():
    stale, why = ConsentRegistry().needs_reconsent("nobody", locale_dir=str(LOCALE_DIR))
    assert not stale
    assert why == "not enrolled"


def test_withdrawal_removes_the_receipt_too():
    """Keeping it would leave a record of what a withdrawn person had agreed to,
    which is content the purge is meant to remove."""
    registry = ConsentRegistry()
    registry.enrol_with_receipt("p1", ALL_DOMAINS, welfare_contact=True,
                                locale="en", locale_dir=str(LOCALE_DIR), at=AT)
    registry.revoke("p1", at=AT)
    assert registry.receipt_for("p1") is None


def test_the_consent_state_the_gates_see_carries_no_language():
    """The decision layer has no business knowing what language somebody speaks."""
    from samvedna.core.types import ConsentState

    fields = set(ConsentState.__dataclass_fields__)
    for forbidden in ("locale", "language", "text_version", "receipt"):
        assert forbidden not in fields


def test_a_consent_ledger_entry_carries_the_locale_and_version():
    registry = ConsentRegistry()
    ledger = Ledger()
    _, receipt = registry.enrol_with_receipt(
        "p1", ALL_DOMAINS, welfare_contact=True, locale="en",
        locale_dir=str(LOCALE_DIR), at=AT,
    )
    ledger.append(actor="personnel:p1", action="consent.granted", subject_pid="p1",
                  purpose="welfare:self", detail=receipt.to_ledger_detail(), at=AT)
    entry = ledger.for_action("consent.granted")[0]
    assert entry.detail["locale"] == "en"
    assert entry.detail["text_version"]
    assert ledger.verify()[0]
