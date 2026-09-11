"""Package a *neighbouring* project for email, without its secrets or its data.

`tools/package.py` packages SAMVEDNA and knows SAMVEDNA's shape. This one is
for the other projects sitting beside it in a directory that is about to be
deleted — it assumes nothing about layout and is deliberately paranoid about
what it picks up, because those projects were not written to be mailed and
nobody has audited them for it.

Three categories are refused outright, and the distinction between them
matters when you read the summary it prints:

**Secrets** — `.env`, `*.pem`, `*.key`, anything credential-shaped. These
projects hold live third-party API keys. Emailing one is worse than losing the
project: a key in a mailbox is a key in every backup, every archive and every
gateway log it passed through, and it stays valid until somebody revokes it.
Rather than dropping them silently, a `.env.example` is written from the real
file's **key names only**, so the recipient knows exactly what to supply.

**Data** — `*.db`, `*.sqlite`, `*.wav`, `*.mp3`, media. One of these projects
carries a clinical database and a real consultation recording. Neither is the
project; both are somebody's information.

**Rebuildables** — `.venv`, `node_modules`, `.git`, caches. 2 GB on disk that
is 15 MB of actual source.

The examples below name no directory in particular, and that is not
squeamishness: `tools/portability_check.py` fails the build on a
sibling-project name anywhere in this tree, so that SAMVEDNA can be shown to
stand alone. A usage example is prose rather than a dependency — but the tool
takes any path and gains nothing from naming one, so the honest fix was to
stop naming them rather than to add an exemption and weaken the check.

Usage:
    uv run python tools/package_sibling.py ../some-project
    uv run python tools/package_sibling.py ../another --split 2
    uv run python tools/package_sibling.py .. --only-files    # loose documents
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mailsafe import encode, encode_split  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

REBUILDABLE = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".next", ".turbo",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "dist", "build", ".idea",
    ".vscode", ".hypothesis", "coverage", ".next-check", "artefacts",
    ".gradle", "target", ".tox", "site-packages",
}

#: Operating-system litter. Harmless-looking, and `.DS_Store` records the
#: directory listing and icon positions of the folder it sits in — including
#: names of files that were deleted before packaging.
JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized"}

#: Credential-shaped. Never packaged; a `.example` is written instead.
SECRET_NAMES = {".env", ".env.local", ".env.production", "credentials.json"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".jks"}

#: Somebody's information, not the project.
DATA_SUFFIXES = {
    ".db", ".sqlite", ".sqlite3", ".wav", ".mp3", ".m4a", ".flac", ".ogg",
    ".mp4", ".mov", ".parquet", ".h5", ".pkl", ".joblib",
}

#: Mail gateways block these outright, inside archives as well as attached.
BLOCKED_SUFFIXES = {
    ".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".msi", ".jar", ".vbs",
    ".ps1", ".app", ".pkg", ".dmg",
}

#: A file bigger than this is almost certainly not source.
LARGE_FILE_BYTES = 5 * 1024 * 1024


def classify(path: Path, root: Path) -> str:
    """Why a file is or is not going in. One of: keep, secret, data, big, blocked."""
    if any(part in REBUILDABLE for part in path.relative_to(root).parts):
        return "rebuildable"
    if path.name in JUNK_NAMES:
        return "rebuildable"
    if path.name in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES:
        return "secret"
    lowered = path.name.lower()
    if path.suffix.lower() in DATA_SUFFIXES or any(
        m in lowered for m in (".db", ".sqlite")
    ):
        return "data"
    if path.suffix.lower() in BLOCKED_SUFFIXES:
        return "blocked"
    if path.stat().st_size > LARGE_FILE_BYTES:
        return "big"
    return "keep"


def env_example(env_file: Path) -> str:
    """A template from a real `.env`: every key, no value, ever.

    Written by matching the key at the start of a line and discarding the rest
    of it. Nothing downstream of the `=` is read into memory beyond the line
    itself, and nothing is written.
    """
    lines = ["# Keys this project expects. Values are NOT included — supply your own.",
             f"# Generated from {env_file.name} by tools/package_sibling.py.", ""]
    for raw in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", raw)
        if match:
            lines.append(f"{match.group(1)}=")
    return "\n".join(lines) + "\n"


def transfer_note(name: str, report: dict, source: Path) -> str:
    """The note that goes *inside* the archive.

    Written from the exclusion report rather than by hand, so it cannot drift
    from what was actually withheld, and so a project with nothing withheld
    does not carry a warning about secrets it never had.

    It exists because the first version of this tool put the explanation in a
    README next to the archives — on the machine being deleted. A recipient
    unzipped source with no record that a `.env` had been removed, no idea the
    database was missing rather than empty, and nothing telling them what to
    supply. An archive has to explain itself; the covering note does not
    survive the journey.
    """
    secrets = report["excluded"]["secret"]
    data = report["excluded"]["data"]
    big = report["excluded"]["big"]
    blocked = report["excluded"]["blocked"]

    out = [
        f"# {name} — what arrived, and what did not",
        "",
        "Packaged for email by SAMVEDNA's `tools/package_sibling.py`. The source",
        "is complete. Three categories were deliberately withheld, and this file",
        "is the record of which — generated from the packaging run, not written",
        "by hand.",
        "",
    ]

    if secrets:
        out += [
            "## Credentials — withheld, and you must supply your own",
            "",
            "These files held live third-party API keys and were **not** sent:",
            "",
        ]
        out += [f"- `{item}`" for item in secrets]
        out += [
            "",
            "A key in a mailbox is a key in every backup, archive and gateway log",
            "the message passed through, and it stays valid until somebody revokes",
            "it. Mailing one is worse than losing the project.",
            "",
            "A `.example` sits beside each — **every key name, no value**. To run:",
            "",
            "```bash",
        ]
        # Paths stay relative to the project root throughout. An earlier
        # version emitted `cd backend && cp ...` followed by
        # `$EDITOR backend/.env`, which does not resolve after the cd — and
        # these are lines somebody pastes rather than reads.
        for item in secrets:
            out.append(f"cp {item}.example {item}")
        out += [
            f"$EDITOR {secrets[0]}",
            "```",
            "",
            "Then fill in the keys you hold. If a project documents an offline or",
            "fallback mode, it will start with the example file unchanged — check",
            "its own README before assuming you need every key.",
            "",
        ]

    if data:
        out += [
            "## Data — withheld, because it is not the project",
            "",
            "Not sent, and not recoverable from this archive:",
            "",
        ]
        for item in data:
            full = source / item
            size = f"{full.stat().st_size / 1048576:.2f} MB" if full.exists() else "?"
            out.append(f"- `{item}` ({size})")
        out += [
            "",
            "These are somebody's information rather than code — recordings,",
            "databases, captured media. The application will start with an empty",
            "store and create its own schema on first run. If you need the",
            "original contents, ask the sender directly rather than by email.",
            "",
        ]

    if big:
        out += ["## Large files — withheld", ""]
        out += [f"- `{item}`" for item in big]
        out += ["", "Over 5 MB and almost certainly not source. Ask if you need them.", ""]

    if blocked:
        out += ["## Blocked file types — withheld", ""]
        out += [f"- `{item}`" for item in blocked]
        out += ["", "Mail gateways refuse these inside archives as well as attached.", ""]

    out += [
        "## Rebuildables — skipped, and restore themselves",
        "",
        f"{report['counts']['rebuildable']:,} files: `.venv`, `node_modules`,",
        "`.git`, caches, and `.DS_Store` (which records the directory listing of",
        "the folder it sits in, including files deleted before packaging).",
        "",
        "```bash",
        "uv sync --all-extras          # Python side, if there is one",
        "npm install                   # in whichever directory has package.json",
        "```",
        "",
        "## Nothing here is SAMVEDNA",
        "",
        "The encoded transfer file says `BEGIN SAMVEDNA ARCHIVE` because the",
        "encoder is shared. It does not mean the contents are. SAMVEDNA travels",
        "as its own archive with its own `TRANSFER.md`.",
        "",
    ]
    return "\n".join(out) + "\n"


def package(source: Path, out_dir: Path, *, only_files: bool) -> tuple[Path, dict]:
    source = source.resolve()
    name = source.name or "bundle"
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"{name}-source.zip"

    counts = dict.fromkeys(("keep", "secret", "data", "big", "blocked", "rebuildable"), 0)
    excluded: dict[str, list[str]] = {k: [] for k in counts}
    secrets: list[Path] = []

    candidates = (
        [p for p in source.iterdir() if p.is_file()]
        if only_files
        else [p for p in source.rglob("*") if p.is_file()]
    )

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(candidates):
            # Never descend into the project doing the packaging.
            if ROOT in path.parents or path == ROOT:
                continue
            try:
                verdict = classify(path, source)
            except OSError:
                continue
            counts[verdict] += 1
            if verdict != "keep":
                if verdict != "rebuildable":
                    excluded[verdict].append(str(path.relative_to(source)))
                if verdict == "secret":
                    secrets.append(path)
                continue
            zf.write(path, Path(name) / path.relative_to(source))

        # A template per secret file, so the recipient knows what to supply —
        # unless the project already ships one, in which case theirs is
        # authoritative and writing a second entry under the same name
        # produces a zip with a duplicate member.
        already = set(zf.namelist())
        for secret in secrets:
            target = str(Path(name) / secret.relative_to(source)) + ".example"
            if target in already:
                continue
            zf.writestr(target, env_example(secret))

    report = {"counts": counts, "excluded": excluded,
              "secrets": [str(s.relative_to(source)) for s in secrets]}

    # The note goes inside, so the archive explains itself wherever it lands.
    with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(
            str(Path(name) / "TRANSFER_NOTE.md"),
            transfer_note(name, report, source),
        )

    return archive, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="directory to package")
    parser.add_argument("--out", default="dist/siblings")
    parser.add_argument("--split", type=int, default=0)
    parser.add_argument(
        "--only-files", action="store_true",
        help="loose files in the directory itself, not subdirectories",
    )
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_dir():
        raise SystemExit(f"not a directory: {source}")

    out_dir = ROOT / args.out
    archive, report = package(source, out_dir, only_files=args.only_files)
    size = archive.stat().st_size

    print(f"{source.resolve().name}: {report['counts']['keep']} files "
          f"-> {archive.relative_to(ROOT)} ({size / 1048576:.2f} MB)")

    for kind, label in (
        ("secret", "SECRETS withheld (a .example was written instead)"),
        ("data", "data withheld (somebody's information, not the project)"),
        ("big", f"over {LARGE_FILE_BYTES // 1048576} MB, withheld"),
        ("blocked", "blocked by mail gateways, withheld"),
    ):
        items = report["excluded"][kind]
        if items:
            print(f"  {label}:")
            for item in items[:8]:
                print(f"    - {item}")
            if len(items) > 8:
                print(f"    … and {len(items) - 8} more")
    if report["counts"]["rebuildable"]:
        print(f"  {report['counts']['rebuildable']:,} rebuildable files skipped "
              f"(.venv, node_modules, .git, caches)")

    if args.split:
        for part in encode_split(archive, args.split, out_dir=out_dir):
            print(f"  -> {part.relative_to(ROOT)} "
                  f"({part.stat().st_size / 1048576:.2f} MB)")
    else:
        text = encode(archive)
        print(f"  -> {text.relative_to(ROOT)} "
              f"({text.stat().st_size / 1048576:.2f} MB)   <- attach this")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
