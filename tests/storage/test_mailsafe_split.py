"""Splitting the archive for a gateway that refuses one 4 MB attachment.

The zip itself is blocked outright by mail gateways, so it travels as base64
text. At 4.24 MB that clears Outlook and Gmail and does not clear a strict
4 MB gateway, which is why splitting exists at all.

What these tests defend is the merge, because a bad merge is the dangerous
outcome. A missing or reordered part can still produce a file that unzips
*partially* — far enough to look like it worked and to leave somebody running
a half-copied system. So every part carries the checksum of the whole archive
rather than of itself, and the merge refuses rather than warns.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import mailsafe  # noqa: E402


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    """A stand-in archive. Random bytes, so nothing compresses or aligns nicely."""
    import os

    target = tmp_path / "samvedna-test.zip"
    target.write_bytes(os.urandom(200_000))
    return target


def test_parts_merge_back_to_the_original_byte_for_byte(archive, tmp_path):
    original = archive.read_bytes()
    parts = mailsafe.encode_split(archive, 2, out_dir=tmp_path)
    archive.unlink()

    assert len(parts) == 2
    merged = mailsafe.decode_parts(parts, out_dir=tmp_path)
    assert merged.read_bytes() == original


@pytest.mark.parametrize("count", [2, 3, 5])
def test_any_number_of_parts_round_trips(archive, tmp_path, count):
    original = archive.read_bytes()
    parts = mailsafe.encode_split(archive, count, out_dir=tmp_path)
    assert len(parts) == count
    assert mailsafe.decode_parts(parts, out_dir=tmp_path).read_bytes() == original


def test_every_part_carries_the_whole_file_checksum(archive, tmp_path):
    """Not its own. A per-part checksum cannot answer the only question."""
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    for part in mailsafe.encode_split(archive, 2, out_dir=tmp_path):
        text = part.read_text(encoding="ascii")
        assert digest in text, f"{part.name} does not carry the whole-file checksum"
        assert "part" in text.lower()


def test_a_missing_part_is_refused_not_silently_short(archive, tmp_path):
    parts = mailsafe.encode_split(archive, 2, out_dir=tmp_path)
    with pytest.raises(SystemExit, match="does not match the checksum"):
        mailsafe.decode_parts(parts[:1], out_dir=tmp_path)


def test_parts_out_of_order_never_produce_the_original(archive, tmp_path):
    """A hand-concatenation in the wrong order must not quietly succeed.

    It fails earlier than the checksum, and for a reason worth recording:
    base64 padding sits at the *end* of the stream, so putting the last part
    first lands `=` in the middle and `b64decode(validate=True)` rejects it
    outright. The checksum in every header is the backstop for the cases where
    padding happens to line up — a three-part split cut on a boundary that
    divides evenly, for instance.
    """
    import base64
    import binascii

    parts = mailsafe.encode_split(archive, 2, out_dir=tmp_path)
    bodies = []
    for part in reversed(parts):
        text = part.read_text(encoding="ascii")
        start = text.index(mailsafe.BEGIN) + len(mailsafe.BEGIN)
        bodies.append("".join(text[start : text.index(mailsafe.END)].split()))

    original = hashlib.sha256(archive.read_bytes()).hexdigest()
    try:
        wrong = base64.b64decode("".join(bodies), validate=True)
    except binascii.Error:
        return  # rejected outright, which is the better failure
    assert hashlib.sha256(wrong).hexdigest() != original, (
        "parts joined in the wrong order produced the original archive"
    )


def test_parts_from_different_archives_are_refused(tmp_path):
    """Two transfers in one inbox is a realistic way to get this wrong."""
    import os

    first = tmp_path / "samvedna-a.zip"
    second = tmp_path / "samvedna-b.zip"
    first.write_bytes(os.urandom(50_000))
    second.write_bytes(os.urandom(50_000))

    a = mailsafe.encode_split(first, 2, out_dir=tmp_path / "a")
    b = mailsafe.encode_split(second, 2, out_dir=tmp_path / "b")

    with pytest.raises(SystemExit, match="different archive"):
        mailsafe.decode_parts([a[0], b[1]], out_dir=tmp_path)


def test_every_part_is_pure_ascii(archive, tmp_path):
    """The instructions must survive a charset conversion too, not just the payload."""
    for part in mailsafe.encode_split(archive, 2, out_dir=tmp_path):
        part.read_bytes().decode("ascii")


def test_the_documented_shell_command_actually_works(archive, tmp_path):
    """Run the one-liner from the header, as a recipient would.

    The single-file version of this header once quoted its own markers inside
    the decode instructions, so the extraction matched the instruction lines
    and produced a zero-byte archive. That was only ever going to be found by
    running the documented command, so it is run here.
    """
    original = archive.read_bytes()
    parts = mailsafe.encode_split(archive, 2, out_dir=tmp_path)
    merged = tmp_path / "rebuilt.zip"

    joined = tmp_path / "joined.txt"
    joined.write_bytes(b"".join(p.read_bytes() for p in sorted(parts)))
    script = (
        f"awk '/^{mailsafe.BEGIN}/{{f=1;next}} /^{mailsafe.END}/{{f=0}} f' "
        f"'{joined}' | base64 -d > '{merged}'"
    )
    subprocess.run(["bash", "-uo", "pipefail", "-c", script], check=True)

    assert merged.read_bytes() == original


def test_one_part_is_refused_as_a_split(archive, tmp_path):
    with pytest.raises(ValueError, match="use encode"):
        mailsafe.encode_split(archive, 1, out_dir=tmp_path)


def test_the_parts_are_each_small_enough_to_be_the_point(archive, tmp_path):
    """A split that does not shrink anything has not solved the problem."""
    whole = mailsafe.encode(archive, out=tmp_path / "whole.txt").stat().st_size
    parts = mailsafe.encode_split(archive, 2, out_dir=tmp_path)
    for part in parts:
        assert part.stat().st_size < whole * 0.75, (
            f"{part.name} is not meaningfully smaller than the single file"
        )
