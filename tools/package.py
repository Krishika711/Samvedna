#!/usr/bin/env python3
"""Build a transferable archive of this project — pendrive or email attachment.

Two different transports, one set of rules. A pendrive cares that nothing in the
tree points back at the machine it was built on. Email cares about that *and*
about size and file types: mail gateways routinely reject attachments over
~20 MB and quarantine archives containing executables, so an archive that
happens to include a 400 MB virtualenv is not a transfer problem to discover at
the far end.

    python tools/package.py                 # writes dist/samvedna-<date>.zip
    python tools/package.py --limit-mb 10   # tighter gateway

Excludes every build artefact and dependency directory. What ships is source,
tests, fixtures, docs and the two setup scripts — everything needed to rebuild,
nothing that can be rebuilt.
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# Rebuildable, machine-specific, or both. None of it travels.
EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".ruff_cache", "artefacts", "dist", "build", ".idea",
    ".next-check",
    ".vscode", ".mypy_cache", "coverage",
    # Hypothesis's example database — the failing inputs it has learned to
    # retry. Rebuildable, machine-local, and it was 112 of 294 files in the
    # archive: more than a third of the manifest was a test cache. Excluding it
    # costs the recipient nothing; Hypothesis rebuilds it on the first run.
    ".hypothesis",
}
# `uv.lock` and `package-lock.json` DO travel. They were excluded at first as
# "machine-specific", which is exactly backwards: a lockfile is what makes the
# copy resolve to the same versions as the original. Without it, unpacking this
# archive on another machine re-resolved `shap` and picked an llvmlite from 2021
# that will not build on a current Python — a failure that only ever appears at
# the far end of the transfer, which is the worst place to find it.
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", ".env", "samvedna.db"}
# `.tsbuildinfo` is TypeScript's incremental-build cache. It is rebuilt on the
# first `tsc` run, it can carry the authoring machine's absolute paths, and a
# stale one on a different machine makes the compiler skip files it should
# check. Nothing good comes of shipping it.
EXCLUDE_SUFFIXES = {
    ".pyc", ".pyo", ".so", ".dylib", ".log", ".db", ".sqlite", ".tsbuildinfo",
}

# Databases and every sidecar they write, matched on a substring rather than a
# suffix.
#
# A suffix set cannot do this: `Path("samvedna.db-wal").suffix` is `".db-wal"`,
# not `".db"`, so the write-ahead log and the shared-memory file sailed past a
# filter that was correctly excluding the database itself. Both shipped in an
# archive — 103 KB of WAL and 32 KB of shm. This particular WAL happened to be
# checkpointed and held nothing, and that is luck: a write-ahead log exists
# precisely to hold writes the main file has not taken yet, which here means
# sealed questionnaire scores and voice medians.
#
# Substring, so a sidecar convention nobody has invented yet is still caught.
EXCLUDE_CONTAINING = (".db", ".sqlite")

# File types mail gateways commonly block outright.
BLOCKED_SUFFIXES = {
    ".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".msi", ".jar", ".vbs",
    ".ps1", ".app", ".pkg", ".dmg",
}

DEFAULT_LIMIT_MB = 20.0


def _included() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.name in EXCLUDE_NAMES or path.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        lowered = path.name.lower()
        if any(marker in lowered for marker in EXCLUDE_CONTAINING):
            continue
        out.append(path)
    return sorted(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-mb", type=float, default=DEFAULT_LIMIT_MB)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "tools"))
    from portability_check import violations  # local import: same tools dir

    found = violations()
    if found:
        print("refusing to package: portability violations present")
        for item in found[:20]:
            print("  " + item)
        return 1

    files = _included()
    blocked = [f for f in files if f.suffix.lower() in BLOCKED_SUFFIXES]
    if blocked:
        print("refusing to package: file types commonly blocked by mail gateways")
        for f in blocked:
            print("  " + f.relative_to(ROOT).as_posix())
        return 1

    DIST.mkdir(exist_ok=True)
    target = Path(args.out) if args.out else DIST / f"samvedna-{date.today():%Y%m%d}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            zf.write(path, Path("samvedna") / path.relative_to(ROOT))

    size_mb = target.stat().st_size / 1_048_576
    print(f"packaged {len(files)} files -> {target.relative_to(ROOT)}  ({size_mb:.2f} MB)")
    if size_mb > args.limit_mb:
        print(f"FAIL: {size_mb:.2f} MB exceeds the {args.limit_mb:.0f} MB attachment limit")
        return 1
    print(f"OK: within the {args.limit_mb:.0f} MB attachment limit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
