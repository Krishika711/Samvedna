#!/usr/bin/env python3
"""Every locale is complete, or it is not offered.

The usual i18n behaviour — fall back to the source language for anything
untranslated — is actively harmful on a consent screen. It puts an English
sentence under a Hindi heading, and a person who reads the Hindi and skips the
line they cannot read has not given informed consent. Worse, nothing anywhere
records that it happened: the screen renders, the button works, and the gap is
invisible to everybody including the person who built it.

So completeness is checked here and the build fails on a gap. A locale with a
missing key is a locale that must not be offered at all.

    python tools/check_locales.py [--strict]

`--strict` additionally fails on any locale still marked `draft`, which is what a
production deployment should run. The default allows drafts, because a draft that
can be read by a reviewer is how it stops being a draft.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "web" / "i18n" / "locales"
SOURCE = "en"

# Keys under _meta describe the file rather than being translated content, so
# they are compared for presence but not for having changed from the source.
META = "_meta"
REQUIRED_META = {
    "locale", "name", "englishName", "direction", "textVersion",
    "reviewStatus", "reviewedBy", "reviewedOn",
}
VALID_STATUS = {"source", "draft", "reviewed"}
VALID_DIRECTION = {"ltr", "rtl"}


def flatten(node, prefix: str = "") -> dict[str, object]:
    """Every leaf path. A list is a leaf, compared by length not content."""
    out: dict[str, object] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def load(locale: str) -> dict:
    return json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))


def check(strict: bool) -> list[str]:
    problems: list[str] = []
    source = load(SOURCE)
    source_flat = flatten(source)
    source_keys = {k for k in source_flat if not k.startswith(f"{META}.")}

    locales = sorted(p.stem for p in LOCALES.glob("*.json"))
    if SOURCE not in locales:
        return [f"the source locale '{SOURCE}' is missing"]

    for locale in locales:
        data = load(locale)
        flat = flatten(data)
        keys = {k for k in flat if not k.startswith(f"{META}.")}

        for key in sorted(source_keys - keys):
            problems.append(f"{locale}: MISSING '{key}'")
        for key in sorted(keys - source_keys):
            problems.append(f"{locale}: EXTRA '{key}' (not in the source locale)")

        # A list whose length differs has silently dropped or invented a bullet.
        for key in sorted(source_keys & keys):
            src, got = source_flat[key], flat[key]
            if isinstance(src, list):
                if not isinstance(got, list):
                    problems.append(f"{locale}: '{key}' should be a list")
                elif len(got) != len(src):
                    problems.append(
                        f"{locale}: '{key}' has {len(got)} items, source has {len(src)}"
                    )
            elif isinstance(got, str) and not got.strip():
                problems.append(f"{locale}: '{key}' is empty")

        meta = data.get(META, {})
        for field in sorted(REQUIRED_META - set(meta)):
            problems.append(f"{locale}: _meta.{field} is missing")
        if meta.get("locale") != locale:
            problems.append(
                f"{locale}: _meta.locale says '{meta.get('locale')}' but the file "
                f"is named '{locale}.json'"
            )
        if meta.get("reviewStatus") not in VALID_STATUS:
            problems.append(
                f"{locale}: _meta.reviewStatus '{meta.get('reviewStatus')}' is not "
                f"one of {sorted(VALID_STATUS)}"
            )
        if meta.get("direction") not in VALID_DIRECTION:
            problems.append(f"{locale}: _meta.direction must be ltr or rtl")
        if meta.get("textVersion") != source[META]["textVersion"]:
            problems.append(
                f"{locale}: textVersion '{meta.get('textVersion')}' does not match "
                f"the source '{source[META]['textVersion']}'. When the source text "
                f"changes, a translation is stale until it is redone — carrying the "
                f"old version forward would let somebody consent to wording nobody "
                f"translated."
            )
        # The language's own name must be in its own script, not the exonym.
        if locale != SOURCE and meta.get("name") == meta.get("englishName"):
            problems.append(
                f"{locale}: _meta.name is the English exonym. A person choosing a "
                f"language must see it written the way they write it."
            )
        if meta.get("reviewStatus") == "reviewed" and not meta.get("reviewedBy"):
            problems.append(f"{locale}: marked reviewed but names no reviewer")
        if strict and meta.get("reviewStatus") == "draft":
            problems.append(
                f"{locale}: still a draft. Consent must not be recorded against an "
                f"unreviewed translation in production."
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    problems = check(args.strict)
    locales = sorted(p.stem for p in LOCALES.glob("*.json"))
    if problems:
        print(f"locales: {len(problems)} problem(s) across {len(locales)} locale(s)")
        for problem in problems:
            print("  " + problem)
        return 1

    reviewed = sum(
        1 for loc in locales if load(loc)[META]["reviewStatus"] in ("source", "reviewed")
    )
    keys = len({k for k in flatten(load(SOURCE)) if not k.startswith(f"{META}.")})
    print(
        f"locales: {len(locales)} complete, {keys} keys each · "
        f"{reviewed} review-complete, {len(locales) - reviewed} draft"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
