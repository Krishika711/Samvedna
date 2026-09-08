"""The verification scripts must be able to fail.

`check.sh` is what closes a phase, and for a while it could not report a
failure from its own most important step. It ran

    uv run python -m pytest tests -q 2>&1 | tail -2

inside a `bash -c` block. A pipeline exits with the status of its *last*
command — `tail`, always 0 — so the transferred copy failed a test, printed
"1 failed" to the screen, and the script still announced ALL CHECKS PASSED.

The subtle part, and the reason the bug was not obvious: `check.sh` **does**
set `-o pipefail` at the top. That option applies to the shell that reads the
file and does not cross a process boundary, so every `bash -c '...'` block
started a fresh shell with pipefail off. The fix was a `block()` helper that
passes the options on the command line, where a block added later cannot
forget them.

A gate that cannot fail is worse than no gate, because it is trusted. So the
property is asserted here rather than left to whoever edits the script next.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = [ROOT / "check.sh", ROOT / "run.sh", ROOT / "tools" / "render_artifacts.sh"]


def _lines(path: Path) -> list[tuple[int, str]]:
    """Numbered lines with comments and blanks removed."""
    out = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append((n, raw))
    return out


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_every_script_sets_pipefail(path: Path) -> None:
    """Without it, `a | b` reports only b's status."""
    text = path.read_text(encoding="utf-8")
    assert re.search(r"^set\s+-[a-z]*o?\s*.*pipefail", text, re.M) or re.search(
        r"^set\s+-[euo]*\s*pipefail", text, re.M
    ), f"{path.name} does not set -o pipefail"


def test_check_sh_spawns_no_shell_without_the_options() -> None:
    """A bare `bash -c` inherits none of this file's `set` options.

    Every inline block must go through `block()`, which passes `-uo pipefail`
    on the command line. This is the check that would have caught the original
    bug at the point it was introduced.
    """
    check = ROOT / "check.sh"
    offenders = [
        (n, line.strip())
        for n, line in _lines(check)
        if re.search(r"\bbash\s+-c\b", line)
    ]
    assert not offenders, (
        "check.sh spawns a shell without its own options — use block() instead:\n"
        + "\n".join(f"  line {n}: {line}" for n, line in offenders)
    )


def test_the_block_helper_exists_and_carries_the_options() -> None:
    check = (ROOT / "check.sh").read_text(encoding="utf-8")
    match = re.search(r"^block\(\)\s*\{(.+?)\}", check, re.M | re.S)
    assert match, "check.sh has no block() helper"
    body = match.group(1)
    assert "pipefail" in body, f"block() does not set pipefail: {body.strip()}"
    assert "-u" in body, f"block() does not set -u: {body.strip()}"


def test_no_pipeline_feeds_a_bare_grep_as_the_success_condition() -> None:
    """`cmd | grep x` passes when cmd fails after printing x.

    The offline-REPLAY step did exactly this. It now captures the run's own
    exit status first and greps the captured log afterwards.
    """
    check = (ROOT / "check.sh").read_text(encoding="utf-8")
    # A pipe into grep/tail on a line that is not obviously reading a file.
    offenders = [
        (n, line.strip())
        for n, line in _lines(ROOT / "check.sh")
        if re.search(r"\|\s*(grep|tail|head)\b", line)
        and "uv run" in line
    ]
    assert not offenders, (
        "a command's exit status is being discarded into grep/tail:\n"
        + "\n".join(f"  line {n}: {line}" for n, line in offenders)
    )
    # And the transfer block must track a status variable explicitly.
    if "runs cold from a transferred copy" in check:
        assert "status=1" in check, (
            "the transfer block does not record a failure status"
        )
