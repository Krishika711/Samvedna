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


# ---------------------------------------------------------------------------
# Asking "who is on this port" must mean "who is listening on it".
#
# `lsof -ti :3100` returns every socket on the port. A browser tab open on the
# console contributes an ESTABLISHED *client* socket owned by Chrome, so with
# the dev server running perfectly normally, `run.sh --status` reported
#
#     :3100 is held by something that is not ours: Google Chrome Helper
#
# and `--stop` refused to free a port this project owned. Looking at the
# console broke restarting it.
# ---------------------------------------------------------------------------

def test_port_queries_ask_only_for_listeners():
    run_sh = ROOT / "run.sh"
    offenders = [
        (n, line.strip())
        for n, line in _lines(run_sh)
        # A port query is `lsof ... :"$port"` or `lsof ... :3100`.
        if re.search(r"lsof[^|]*\s:\"?\$?\w+", line)
        and "-sTCP:LISTEN" not in line
        # `-p <pid>` queries a process, not a port, and needs no state filter.
        and not re.search(r"-p\s", line)
    ]
    assert not offenders, (
        "a port is being queried without -sTCP:LISTEN, so a client connection "
        "(a browser tab on the console) can be mistaken for the server:\n"
        + "\n".join(f"  line {n}: {line}" for n, line in offenders)
    )


def test_there_is_exactly_one_definition_of_who_holds_a_port():
    """Two call sites are two chances to forget the flag.

    There were briefly two, and both were wrong in the same way. The helper
    exists so the next person adding a port check inherits the answer instead
    of rediscovering the bug.
    """
    run_sh = ROOT / "run.sh"
    text = run_sh.read_text(encoding="utf-8")

    assert re.search(r"^listeners_on\(\)\s*\{", text, re.M), (
        "run.sh has no listeners_on() helper"
    )
    # Code only. `_lines` drops comments, which matter here: the helper's own
    # docstring quotes the broken command it replaced, and counting that as a
    # definition would make the guard fail on the correct file.
    definitions = [
        (n, line.strip()) for n, line in _lines(run_sh) if "lsof -ti" in line
    ]
    assert len(definitions) == 1, (
        "`lsof -ti` belongs only inside listeners_on(); found "
        f"{len(definitions)} uses:\n"
        + "\n".join(f"  line {n}: {line}" for n, line in definitions)
    )
