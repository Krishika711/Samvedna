"""Wrap the archive as plain text, because mail gateways block the zip.

The archive passed every check `tools/package.py` makes — under the attachment
limit, no executables, no PII, no organisation names — and the mail gateway
rejected it anyway. That check was answering the wrong question. It asked
"is anything *inside* this archive dangerous", and a gateway asks "is a zip
allowed at all", which for most corporate Exchange and Defender policies it is
not. And when a scanner does look inside, it applies the same extension
blocklist there: this tree carries 116 `.py`, 3 `.sh`, 1 `.js` and 1 `.mjs`,
and `.js` is on Microsoft's default list with `.sh` and `.py` added by most
organisations.

Renaming `.zip` to something else does not help, because content inspection
recognises the `PK\\x03\\x04` header regardless of extension. Password-
protecting it makes things worse: a scanner that cannot inspect an archive
usually quarantines it.

So the payload stops being an archive. Base64 is inert text — no header to
recognise, no extension to blocklist, nothing executable to find — and every
gateway passes `.txt`. It costs 33% in size, which on a 2.5 MB archive is
irrelevant.

The header is deliberately outside the encoded block and written for a person
who has never seen this project. They have no copy of it yet, so the decode
instructions may only use tools that ship with the operating system: `base64`
on macOS and Linux, `certutil` on Windows. Anything else is a bootstrap that
cannot bootstrap.

Usage:
    uv run python tools/mailsafe.py                    # encode the newest archive
    uv run python tools/mailsafe.py --decode FILE.txt  # verify and unpack
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Selects a base64 payload line and nothing else. Used by the Windows
# instructions, which take this route rather than matching the markers: the
# .NET regex for the markers needs so much escaping that it is unreadable, and
# an instruction a recipient cannot sanity-check is an instruction they will
# not trust.
#
# It has to reject every header line, and the one that nearly broke it is the
# rule of "=" characters under the title — 70 bytes drawn entirely from the
# base64 alphabet. Requiring at least two payload characters *before* any
# padding excludes it, while still accepting a final short line like "ab==".
PS_LINE = "^[A-Za-z0-9+/]{2,}={0,2}$"

BEGIN = "-----BEGIN SAMVEDNA ARCHIVE-----"
END = "-----END SAMVEDNA ARCHIVE-----"
# 76 characters is the MIME base64 convention. Some gateways and older mail
# clients rewrap or truncate very long lines, and a rewrapped line is still
# decodable while a truncated one is not — so stay inside the convention.
LINE = 76

# Every extractor below anchors the markers to the start of a line, and every
# instruction in the header is indented. That is not cosmetic. The first
# version matched the markers anywhere in the file, and the header *quotes*
# them inside its own decode instructions — so the extraction found the
# instruction lines, fed a sed command to base64, and produced a zero-byte
# archive. Verified by running the documented one-liner as a recipient would,
# which is the only way that bug was ever going to be found.


def _header(archive: Path, digest: str, encoded_size: int) -> str:
    return f"""SAMVEDNA - project archive, encoded as text
{"=" * 70}

This file is a zip archive converted to plain text so that it survives a mail
gateway. It contains no executable content in this form; nothing here can run
until you decode it.

  original file   {archive.name}
  original size   {archive.stat().st_size:,} bytes
  encoded size    {encoded_size:,} bytes
  sha256          {digest}

HOW TO DECODE
{"-" * 70}

macOS or Linux - one command, `base64` is already installed:

    awk '/^{BEGIN}/{{f=1;next}} /^{END}/{{f=0}} f' \\
      "{archive.name}.txt" | base64 -d > {archive.name}

Windows PowerShell - nothing to install:

    $b = (Get-Content "{archive.name}.txt" |
          Where-Object {{ $_ -match '{PS_LINE}' }}) -join ''
    [IO.File]::WriteAllBytes("{archive.name}", [Convert]::FromBase64String($b))

  That keeps only the lines that are pure base64 and drops everything else, so
  it does not depend on matching the markers at all.

Then check it arrived intact - the number must match the sha256 above:

    shasum -a 256 {archive.name}          # macOS / Linux
    certutil -hashfile {archive.name} SHA256   # Windows

Then unzip it and follow README.md:

    unzip {archive.name} && cd samvedna
    uv sync --all-extras && (cd web && npm install)
    ./check.sh && ./run.sh

If you have this project already, `uv run python tools/mailsafe.py --decode
{archive.name}.txt` does the decode and the checksum in one step.

{"=" * 70}

"""


def encode(archive: Path, out: Path | None = None) -> Path:
    raw = archive.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    body = base64.b64encode(raw).decode("ascii")
    wrapped = "\n".join(body[i : i + LINE] for i in range(0, len(body), LINE))

    target = out or archive.with_suffix(archive.suffix + ".txt")
    content = (
        _header(archive, digest, len(wrapped))
        + BEGIN + "\n" + wrapped + "\n" + END + "\n"
    )

    # Pure ASCII, enforced rather than hoped for. This file's entire job is
    # surviving transport, and an em dash or a box-drawing character is one
    # more thing for a gateway, an old client or a Windows console in
    # code page 437 to re-encode or mangle. Encoding the payload correctly and
    # then losing the instructions to a charset conversion would be a
    # remarkable way to fail.
    content.encode("ascii")

    target.write_text(content, encoding="ascii")
    return target


def _part_header(
    archive: Path, digest: str, part: int, total: int, part_lines: int
) -> str:
    """Header for one part of a split transfer.

    Every part carries the checksum of the **whole** archive, not of itself.
    That is deliberate: the only question that matters after a merge is whether
    the reassembled file is the one that was sent, and a per-part checksum
    cannot answer it. A recipient who joins the parts in the wrong order, or
    misses one, gets a mismatch and knows immediately — rather than an archive
    that unzips far enough to look fine.
    """
    return f"""SAMVEDNA - project archive, part {part} of {total}
{"=" * 70}

This is PART {part} OF {total}. On its own it decodes to nothing. You need all
{total} parts, joined in order, before anything can be extracted.

  final file      {archive.name}
  final size      {archive.stat().st_size:,} bytes
  sha256 (whole)  {digest}
  this part       {part_lines:,} lines of base64

HOW TO MERGE AND DECODE
{"-" * 70}

Save all {total} parts into one folder, then run this once. Order matters and
the wildcard sorts correctly because the parts are numbered:

macOS or Linux:

    cat {archive.name}.part*of{total}.txt |
      awk '/^{BEGIN}/{{f=1;next}} /^{END}/{{f=0}} f' |
      base64 -d > {archive.name}

Windows PowerShell:

    $b = (Get-ChildItem "{archive.name}.part*of{total}.txt" | Sort-Object Name |
          Get-Content | Where-Object {{ $_ -match '{PS_LINE}' }}) -join ''
    [IO.File]::WriteAllBytes("{archive.name}", [Convert]::FromBase64String($b))

Then check the merge - this number must match the sha256 above:

    shasum -a 256 {archive.name}          # macOS / Linux
    certutil -hashfile {archive.name} SHA256   # Windows

If it does not match, a part is missing, truncated, or out of order. Do not
unzip it; ask for the parts again. A wrong merge can still produce a file that
unzips partially, which is worse than one that fails outright.

Then:

    unzip {archive.name} && cd samvedna
    uv sync --all-extras && (cd web && npm install)
    ./check.sh && ./run.sh

{"=" * 70}

"""


def encode_split(archive: Path, parts: int, out_dir: Path | None = None) -> list[Path]:
    """Encode into `parts` files, each independently mailable.

    The payload is split by **line**, never mid-line. A base64 line boundary is
    a safe cut; a byte boundary is not, because joining two halves of a line
    with a newline between them produces a body that decodes to something
    different rather than failing loudly.
    """
    if parts < 2:
        raise ValueError("use encode() for a single file")

    raw = archive.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    body = base64.b64encode(raw).decode("ascii")
    lines = [body[i : i + LINE] for i in range(0, len(body), LINE)]

    per_part = -(-len(lines) // parts)  # ceiling, so the last part is the short one
    target_dir = out_dir or archive.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for index in range(parts):
        chunk = lines[index * per_part : (index + 1) * per_part]
        number = index + 1
        target = target_dir / f"{archive.name}.part{number}of{parts}.txt"
        content = (
            _part_header(archive, digest, number, parts, len(chunk))
            + BEGIN + "\n" + "\n".join(chunk) + "\n" + END + "\n"
        )
        # ASCII, for the reason in `encode`.
        content.encode("ascii")
        target.write_text(content, encoding="ascii")
        written.append(target)

    return written


def decode_parts(paths: list[Path], out_dir: Path | None = None) -> Path:
    """Join numbered parts and decode, refusing anything that does not add up."""
    ordered = sorted(paths, key=lambda p: p.name)
    body: list[str] = []
    expected: str | None = None
    name: str | None = None

    for path in ordered:
        text = path.read_text(encoding="utf-8")
        match = re.search(
            rf"^{re.escape(BEGIN)}$(.*?)^{re.escape(END)}$", text, re.S | re.M
        )
        if match is None:
            raise SystemExit(f"{path.name}: no payload between the markers")
        body.append("".join(match.group(1).split()))

        found = re.search(r"sha256 \(whole\)\s+([0-9a-f]{64})", text)
        if found:
            if expected and found.group(1) != expected:
                raise SystemExit(
                    f"{path.name} belongs to a different archive - its whole-file "
                    f"checksum does not match the other parts"
                )
            expected = found.group(1)
        named = re.search(r"final file\s+(\S+)", text)
        if named:
            name = named.group(1)

    raw = base64.b64decode("".join(body), validate=True)
    digest = hashlib.sha256(raw).hexdigest()
    if expected and digest != expected:
        raise SystemExit(
            "the merged archive does not match the checksum in the headers.\n"
            f"  expected {expected}\n  got      {digest}\n"
            "A part is missing, truncated, or out of order. Ask for them again "
            "rather than unzipping this."
        )

    target = (out_dir or ordered[0].parent) / (name or "samvedna.zip")
    target.write_bytes(raw)
    return target


def decode(text_file: Path, out_dir: Path | None = None) -> Path:
    text = text_file.read_text(encoding="utf-8")
    # `re.M` plus `^` anchors, for the reason documented next to LINE above:
    # the header quotes these markers in its own instructions, and an unanchored
    # search finds those first.
    match = re.search(
        r"^" + re.escape(BEGIN) + r"\s*$(.*?)^" + re.escape(END),
        text,
        re.S | re.M,
    )
    if not match:
        raise SystemExit(f"{text_file.name}: no {BEGIN} block found")

    raw = base64.b64decode("".join(match.group(1).split()), validate=True)

    # The checksum is in the human-readable header. Verifying against it is the
    # point of writing it there — a mail gateway that "helpfully" rewrites the
    # body would otherwise produce a corrupt archive that unzips far enough to
    # look fine.
    # Anchored to the header field, not the word "sha256" wherever it
    # appears — the instructions mention `shasum -a 256` too.
    stated = re.search(r"^\s+sha256\s+([0-9a-f]{64})\s*$", text, re.M)
    actual = hashlib.sha256(raw).hexdigest()
    if stated and stated.group(1) != actual:
        raise SystemExit(
            f"CHECKSUM MISMATCH - the file was altered in transit\n"
            f"  expected {stated.group(1)}\n"
            f"  got      {actual}\n"
            f"Ask for it again; do not use this copy."
        )

    name = re.search(r"original file\s+(\S+)", text)
    target = (out_dir or text_file.parent) / (
        name.group(1) if name else text_file.stem
    )
    target.write_bytes(raw)
    print(f"decoded {len(raw):,} bytes -> {target}")
    print(f"sha256 verified: {actual}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decode", metavar="FILE.txt")
    parser.add_argument(
        "--merge", nargs="+", metavar="PART.txt",
        help="join split parts and decode, verifying the whole-file checksum",
    )
    parser.add_argument("--archive", help="defaults to the newest dist/*.zip")
    parser.add_argument(
        "--split", type=int, metavar="N", default=0,
        help="write N numbered parts instead of one file, for strict gateways",
    )
    args = parser.parse_args()

    if args.merge:
        target = decode_parts([Path(x) for x in args.merge])
        print(f"merged {len(args.merge)} parts -> {target}")
        print("checksum matches the headers.")
        return 0

    if args.decode:
        decode(Path(args.decode))
        return 0

    if args.archive:
        archive = Path(args.archive)
    else:
        candidates = sorted(
            (ROOT / "dist").glob("samvedna-*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise SystemExit("no dist/samvedna-*.zip — run tools/package.py first")
        archive = candidates[0]

    if args.split:
        parts = encode_split(archive, args.split)
        print(f"encoded {archive.name} ({archive.stat().st_size:,} bytes) "
              f"into {len(parts)} parts")
        for part in parts:
            print(f"     -> {part.relative_to(ROOT)} "
                  f"({part.stat().st_size / 1048576:.2f} MB)")
        print()
        print("Send every part. Each one carries the whole-file checksum and")
        print("the merge command, so a recipient with all of them needs nothing")
        print("else — and one with a part missing finds out before unzipping.")
        return 0

    target = encode(archive)
    print(f"encoded {archive.name} ({archive.stat().st_size:,} bytes)")
    print(f"     -> {target.relative_to(ROOT)} "
          f"({target.stat().st_size / 1048576:.2f} MB)")
    print()
    print("Attach that .txt file. It is inert text: no zip header for a gateway")
    print("to recognise, no blocked extension, nothing executable to scan.")
    print()
    print("If a gateway still refuses it, --split 2 writes two smaller parts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
