"""The archive has to survive a mail gateway, and the instructions have to work.

`tools/package.py` checked that nothing *inside* the archive was dangerous and
declared it sendable. The gateway rejected it anyway, because a gateway asks a
different question: is a zip allowed at all. For most corporate Exchange and
Defender policies it is not, and when a scanner does look inside it applies the
same extension blocklist there — this tree carries 116 `.py`, 3 `.sh`, 1 `.js`
and 1 `.mjs`, and `.js` is on Microsoft's default list.

So `tools/mailsafe.py` converts the archive to base64 text. What these tests
defend is not the encoding — base64 is not this project's to get wrong — but
the two things that actually failed:

1. **The extraction markers must anchor to the start of a line.** The header
   quotes them inside its own decode instructions, so an unanchored search
   finds the instructions, feeds a shell command to `base64`, and produces a
   zero-byte archive. That is exactly what the first version did, and it was
   only caught by running the documented one-liner as a recipient would.

2. **The documented commands must work.** They are the whole deliverable: a
   recipient has no copy of this project, so they can only use tools that ship
   with the operating system. An instruction that does not work is worse than
   no instruction, because they will assume the file is corrupt.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from mailsafe import BEGIN, END, LINE, PS_LINE, decode, encode  # noqa: E402


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    """A small stand-in. The content only has to be binary and non-trivial."""
    payload = bytes(range(256)) * 40
    target = tmp_path / "samvedna-test.zip"
    target.write_bytes(payload)
    return target


def test_round_trip_is_byte_identical(archive: Path, tmp_path: Path):
    encoded = encode(archive)
    original = archive.read_bytes()
    archive.unlink()

    decode(encoded, out_dir=tmp_path)

    assert archive.read_bytes() == original


def test_the_markers_are_anchored_at_the_start_of_a_line(archive: Path):
    """The bug that shipped, stated as a property.

    The header *must* quote the markers — the instructions are useless without
    them — so the extraction must be anchored instead. This asserts both: the
    markers appear more than once, and only one occurrence of each is at column
    zero.
    """
    text = encode(archive).read_text()

    assert text.count(BEGIN) > 1, (
        "the header no longer quotes the marker in its instructions — if that "
        "is deliberate, this test is obsolete; if not, the instructions are "
        "now incomplete"
    )
    assert len(re.findall(rf"^{re.escape(BEGIN)}\s*$", text, re.M)) == 1
    assert len(re.findall(rf"^{re.escape(END)}\s*$", text, re.M)) == 1


def test_an_unanchored_extraction_would_have_failed(archive: Path):
    """Proof the anchoring is load-bearing rather than defensive decoration."""
    text = encode(archive).read_text()

    naive = re.search(re.escape(BEGIN) + r"(.*?)" + re.escape(END), text, re.S)
    assert naive is not None
    with pytest.raises(binascii.Error):
        # The naive match grabs the instruction text between the two quoted
        # markers, which is not valid base64.
        base64.b64decode("".join(naive.group(1).split()), validate=True)


def test_the_documented_shell_command_works(archive: Path, tmp_path: Path):
    """Run the awk one-liner out of the header, verbatim, and compare bytes.

    The command is extracted from the generated file rather than repeated here,
    so editing the header without editing the command cannot pass this test.
    """
    encoded = encode(archive)
    text = encoded.read_text()
    original = archive.read_bytes()

    match = re.search(r"^\s+(awk '.*?)\|\s*base64 -d", text, re.S | re.M)
    assert match, "the header no longer documents an awk extraction"
    awk_part = match.group(1).replace("\\\n", " ").strip()

    out = tmp_path / "decoded.zip"
    result = subprocess.run(
        f'{awk_part} | base64 -d > "{out}"',
        shell=True, cwd=encoded.parent, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == original, "the documented command produced wrong bytes"


def test_the_stated_checksum_matches_the_payload(archive: Path):
    text = encode(archive).read_text()

    stated = re.search(r"^\s+sha256\s+([0-9a-f]{64})\s*$", text, re.M)
    assert stated, "no sha256 field in the header"
    assert stated.group(1) == hashlib.sha256(archive.read_bytes()).hexdigest()


def test_a_single_altered_character_is_refused(archive: Path, tmp_path: Path):
    """A body-rewriting gateway must not yield a plausible-looking archive.

    Without the checksum this would decode to something that unzips far enough
    to look fine and then fails somewhere unrelated.
    """
    encoded = encode(archive)
    text = encoded.read_text()
    start = re.search(rf"^{re.escape(BEGIN)}\s*$", text, re.M).end() + 1
    flipped = text[:start + 20] + ("A" if text[start + 20] != "A" else "B") + text[start + 21:]

    tampered = tmp_path / "tampered.txt"
    tampered.write_text(flipped)

    # A directory of its own. Decoding into `tmp_path` would land next to the
    # fixture's own archive of the same name, and "the file exists" would then
    # prove nothing.
    landing = tmp_path / "landing"
    landing.mkdir()

    with pytest.raises(SystemExit, match="CHECKSUM MISMATCH"):
        decode(tampered, out_dir=landing)

    assert list(landing.iterdir()) == [], (
        "a corrupt archive was written to disk before the checksum was checked"
    )


def test_lines_stay_within_the_mime_convention(archive: Path):
    """Long lines get rewrapped or truncated by some clients.

    A rewrapped line is still decodable; a truncated one is not.
    """
    text = encode(archive).read_text()
    body = re.search(
        rf"^{re.escape(BEGIN)}\s*$(.*?)^{re.escape(END)}", text, re.S | re.M
    ).group(1)
    for line in body.strip().splitlines():
        assert len(line) <= LINE, f"line of {len(line)} chars exceeds {LINE}"


def test_the_encoded_file_carries_no_zip_header(archive: Path):
    """Content inspection recognises PK\\x03\\x04 whatever the extension says.

    This is why renaming the zip does not work and encoding it does.
    """
    raw = encode(archive).read_bytes()
    assert b"PK\x03\x04" not in raw
    # Pure ASCII, so there is nothing for a gateway or an old client to
    # re-encode and nothing a scanner reads as binary.
    raw.decode("ascii")


def test_the_windows_line_filter_selects_exactly_the_payload(archive: Path):
    """The Windows instructions keep base64 lines instead of matching markers.

    That route exists because the .NET regex for the markers needs so much
    escaping it becomes unreadable, and an instruction a recipient cannot
    sanity-check is one they will not trust. It has to be exactly equivalent,
    so that is asserted rather than assumed — and it cannot be run here, since
    there is no PowerShell on the build machine, which makes the equivalence
    the only available evidence.
    """
    text = encode(archive).read_text()
    lines = text.splitlines()

    selected = [ln for ln in lines if re.match(PS_LINE, ln)]
    marker_based = re.search(
        rf"^{re.escape(BEGIN)}\s*$(.*?)^{re.escape(END)}", text, re.S | re.M
    ).group(1).strip().splitlines()

    assert selected == marker_based, (
        "the Windows filter and the marker extraction disagree"
    )
    assert base64.b64decode("".join(selected), validate=True) == archive.read_bytes()


def test_the_line_filter_rejects_every_header_line(archive: Path):
    """Including the one that nearly broke it.

    The rule under the title is 70 characters of "=", drawn entirely from the
    base64 alphabet. A filter of `^[A-Za-z0-9+/=]+$` accepts it and corrupts
    the payload; requiring two payload characters before any padding does not.
    """
    text = encode(archive).read_text()
    header = text.split(BEGIN)[0]

    for line in header.splitlines():
        if not line.strip():
            continue
        assert not re.match(PS_LINE, line), f"header line would be decoded: {line!r}"

    assert not re.match(PS_LINE, "=" * 70)
    # ...but a genuine short final line with padding must still be kept.
    assert re.match(PS_LINE, "ab==")
    assert re.match(PS_LINE, "YWJjZA==")
