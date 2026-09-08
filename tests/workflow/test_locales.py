"""Every locale is complete, or it is not offered.

The failure this guards against is not a crash. It is a consent screen that
renders successfully with an English sentence under a Hindi heading, which a
person can agree to without having read it, and which nothing anywhere records.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
LOCALE_DIR = ROOT / "web" / "i18n" / "locales"
sys.path.insert(0, str(ROOT / "tools"))

from check_locales import check, flatten, load  # noqa: E402

CODES = sorted(p.stem for p in LOCALE_DIR.glob("*.json"))


def test_the_checker_passes_on_the_shipped_locales():
    assert check(strict=False) == []


def test_there_is_more_than_one_language():
    assert len(CODES) >= 2
    assert "en" in CODES


@pytest.mark.parametrize("code", CODES)
def test_every_locale_has_exactly_the_source_keys(code):
    source = {k for k in flatten(load("en")) if not k.startswith("_meta.")}
    got = {k for k in flatten(load(code)) if not k.startswith("_meta.")}
    assert got == source, f"{code}: {source ^ got}"


@pytest.mark.parametrize("code", CODES)
def test_no_translated_string_is_empty(code):
    """`_meta` is excluded: `reviewedBy` is legitimately empty on a draft, which
    is exactly what marks it as unreviewed. The checker asserts separately that a
    locale claiming `reviewed` names a reviewer."""
    for key, value in flatten(load(code)).items():
        if key.startswith("_meta."):
            continue
        if isinstance(value, str):
            assert value.strip(), f"{code}: '{key}' is empty"


@pytest.mark.parametrize("code", CODES)
def test_a_locale_claiming_review_names_its_reviewer(code):
    meta = load(code)["_meta"]
    if meta["reviewStatus"] == "reviewed":
        assert meta["reviewedBy"].strip(), f"{code} claims review but names nobody"
        assert meta["reviewedOn"].strip()


@pytest.mark.parametrize("code", [c for c in CODES if c != "en"])
def test_no_locale_is_an_untranslated_copy_of_english(code):
    """A locale file copied and not translated passes every structural check.
    Comparing the actual strings is the only thing that catches it."""
    source = flatten(load("en"))
    got = flatten(load(code))
    identical = [
        k for k, v in got.items()
        if not k.startswith("_meta.") and isinstance(v, str) and v == source.get(k)
    ]
    assert not identical, f"{code}: {len(identical)} strings are still English: {identical[:3]}"


@pytest.mark.parametrize("code", CODES)
def test_list_lengths_match_the_source(code):
    """A dropped bullet is a promise the person was never shown."""
    source, got = flatten(load("en")), flatten(load(code))
    for key, value in source.items():
        if isinstance(value, list):
            assert len(got[key]) == len(value), f"{code}: '{key}' lost or gained an item"


@pytest.mark.parametrize("code", CODES)
def test_the_acr_promise_survives_translation(code):
    """The single most important sentence on the page: this is never used for
    ACR, promotion, posting or discipline. It must be present in every language,
    and the acronym is deliberately left untranslated because that is how it
    appears on the document a jawan actually holds."""
    never = load(code)["transparency"]["never"]
    assert any("ACR" in line for line in never), f"{code} lost the ACR promise"


@pytest.mark.parametrize("code", CODES)
def test_the_withdrawal_promise_survives_translation(code):
    """'Nobody is told' is the sentence that makes withdrawal safe to use."""
    data = load(code)
    assert data["withdraw"]["doneNobodyTold"].strip()
    assert data["withdraw"]["body"].strip()


def test_a_missing_key_is_detected(tmp_path):
    import shutil

    import check_locales

    shutil.copytree(LOCALE_DIR, tmp_path / "loc")
    target = tmp_path / "loc" / "hi.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    del payload["withdraw"]["button"]
    target.write_text(json.dumps(payload, ensure_ascii=False))

    original = check_locales.LOCALES
    try:
        check_locales.LOCALES = tmp_path / "loc"
        problems = check_locales.check(strict=False)
    finally:
        check_locales.LOCALES = original
    assert any("MISSING 'withdraw.button'" in p for p in problems)


def test_a_stale_text_version_is_detected(tmp_path):
    """When the source text changes, a translation is stale until it is redone.
    Carrying the old version forward would let somebody consent to wording
    nobody translated."""
    import shutil

    import check_locales

    shutil.copytree(LOCALE_DIR, tmp_path / "loc")
    target = tmp_path / "loc" / "hi.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["_meta"]["textVersion"] = "1999.01.01-1"
    target.write_text(json.dumps(payload, ensure_ascii=False))

    original = check_locales.LOCALES
    try:
        check_locales.LOCALES = tmp_path / "loc"
        problems = check_locales.check(strict=False)
    finally:
        check_locales.LOCALES = original
    assert any("textVersion" in p and "stale" in p for p in problems)


def test_strict_mode_rejects_drafts():
    """What a production deployment runs. Drafts are allowed by default because
    a draft a reviewer can read is how it stops being a draft."""
    problems = check(strict=True)
    assert problems
    assert all("still a draft" in p for p in problems)


def test_no_locale_file_reaches_an_external_service():
    """The strings ship in the repository, which is also what makes them
    reviewable. No translation API is called at build time or run time."""
    for path in LOCALE_DIR.glob("*.json"):
        blob = path.read_text(encoding="utf-8")
        for marker in ("http://", "https://", "api_key", "translate.google"):
            assert marker not in blob, f"{path.name} contains {marker}"
