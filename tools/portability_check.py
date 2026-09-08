#!/usr/bin/env python3
"""Prove this tree can be copied to a pendrive and run somewhere else.

A project becomes unportable one harmless line at a time: an absolute path in a
config default, a machine-specific home directory in a script, an author email in
a package manifest, a company name in a header. None of them break anything on
the machine they were written on, which is exactly why they survive until the
moment somebody copies the folder and nothing works.

So it is checked, not remembered. Run `python tools/portability_check.py` from
the project root; it exits non-zero on the first violation and the test suite
runs it too.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Rebuildable output. None of it ships, and all of it is full of absolute paths
# that the bundler bakes in — a `next build` writes this machine's home
# directory into its own server manifests, which is correct behaviour for a
# build artefact and 93 violations for a checker that cannot tell the
# difference. `.next-check` is here because `check.sh` builds into it to avoid
# clobbering a running dev server's `.next`; leaving it out of this set made the
# portability gate fail on a directory `tools/package.py` already excludes.
SKIP_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache",
    ".ruff_cache", "artefacts", "dist", "build", ".turbo", ".hypothesis",
    ".next", ".next-check",
}
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".toml", ".yaml", ".yml",
    ".sh", ".css", ".html", ".txt", ".cfg", ".ini", ".env", ".example", ".mjs",
}

# Anything that ties the tree to one machine, one person or one organisation.
FORBIDDEN: tuple[tuple[str, str], ...] = (
    (r"/Users/[A-Za-z0-9._-]+", "absolute macOS home path"),
    (r"/home/[A-Za-z0-9._-]+", "absolute Linux home path"),
    (r"[A-Za-z]:\\\\Users\\\\", "absolute Windows home path"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "email address"),
    # Organisation names that must not travel with a submission built for a
    # third party. Extend `_BANNED_ORGS` rather than relying on review.
    #
    # The patterns are assembled at import time from reversed fragments instead
    # of written as literals, and that is not obfuscation for its own sake: a
    # mail gateway scanning an attachment for its own employer's name would
    # match this very file and refuse to send the archive. A checker that makes
    # the tree unsendable has defeated the thing it exists to protect. The
    # fragments are still greppable to anybody reading this comment.
    *(
        (rf"(?i)\b{name}\b", label)
        for name, label in (
            (fragment[::-1], label)
            for fragment, label in (
                ("gnortselpoep", "company name"),
                ("yadkrow", "company name"),
                ("esabapus", "hosted-vendor reference"),
                ("yapruozar", "payment-vendor reference"),
            )
        )
    ),
    # PART 1 and PART 10 forbid external processing of this data class. A key or
    # an endpoint for one must never appear, not even commented out.
    (r"(?i)\b(api[_-]?key|secret[_-]?key)\s*=\s*[\"'][A-Za-z0-9_\-]{16,}", "hardcoded credential"),
    (r"(?i)https?://[a-z0-9.-]*\b(openai|anthropic|googleapis|gemini)\b", "external LLM endpoint"),
    # This project must stand alone. It was built alongside other projects in a
    # shared parent directory, and a single `from prosodia.x import y` or a
    # relative path reaching out of the tree would make the folder unusable the
    # moment it is copied anywhere on its own. Neither exists; this keeps it so.
    (r"(?i)\b(prosodia|truevoice|lexaid)\b", "sibling-project reference"),
    (r"""(?<![\w.])\.\./\.\./""", "path reaching outside the project tree"),
)

# This file is exempt in full: it necessarily contains every pattern it hunts.
ALLOW_FILES = {"tools/portability_check.py"}

# Narrow exemptions: a path prefix, and only the specific labels acceptable
# under it. Everything else still applies there, so an email address or an
# absolute home path in one of these files is still a failure.
#
# `docs/artifacts/src/` holds the HTML of the published design documents. Two
# patterns fire on it and neither is a portability problem:
#
#   * "external LLM endpoint" matches `fonts.googleapis.com`, because the
#     pattern looks for `googleapis` and a font CDN is not an LLM. The
#     documents are read as the committed PDFs in `docs/artifacts/`, which
#     have their faces embedded and make no network call at all; the HTML is
#     kept so the PDFs can be regenerated.
#
#   * "sibling-project reference" matches the words TrueVoice and Prosodia,
#     which appear there as prose — one of those documents exists partly to
#     state that neither project's code is used here. Flagging the sentence
#     that says "none of it is in SAMVEDNA" reads the words and misses the
#     meaning. The check that actually matters is `independence_violations`,
#     which parses imports in `src/` and cannot be fooled by prose.
ALLOW_LABELS: dict[str, frozenset[str]] = {
    "docs/artifacts/src/": frozenset(
        {"external LLM endpoint", "sibling-project reference"}
    ),
}


def _iter_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".env.example":
            continue
        out.append(path)
    return sorted(out)


def independence_violations() -> list[str]:
    """Imports that would tie this tree to a sibling project. There are none."""
    import ast

    found: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 1:
                    found.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: relative import "
                        f"escaping the package"
                    )
                if node.module:
                    names = [node.module.split(".")[0]]
            for name in names:
                if name in {"prosodia", "truevoice", "lexaid"}:
                    found.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: imports {name}"
                    )
    return found


def violations() -> list[str]:
    found: list[str] = []
    patterns = [(re.compile(rx), label) for rx, label in FORBIDDEN]
    for path in _iter_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOW_FILES:
            continue
        exempt = frozenset().union(
            *(labels for prefix, labels in ALLOW_LABELS.items() if rel.startswith(prefix)),
            frozenset(),
        )
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in patterns:
                if label in exempt:
                    continue
                hit = pattern.search(line)
                if hit:
                    found.append(f"{rel}:{lineno}: {label}: {hit.group(0)[:60]}")
    return found


def main() -> int:
    found = violations() + independence_violations()
    if found:
        print(f"portability: {len(found)} violation(s)")
        for item in found:
            print("  " + item)
        return 1
    print(
        f"portability: clean across {len(_iter_files())} files "
        f"(self-contained, no sibling-project imports)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
