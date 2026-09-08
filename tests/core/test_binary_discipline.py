"""Binary data must not pass through text operations.

Checked mechanically rather than by review, for the same reason as
`test_config_discipline.py`: the discipline only holds if breaking it is noisy.

This exists because of one line that shipped:

    path.read_bytes().strip()

`bytes.strip()` with no argument removes ASCII whitespace — space, tab,
newline, carriage return, vertical tab, form feed. Applied to a 32-byte
encryption key, it silently shortened roughly **one key in twenty-one**, since
a random key begins or ends with one of those six bytes about 4.7% of the time.
In a deployment that is a key rotation with a one-in-twenty chance of the
system refusing to start; with a looser length check it would instead have been
a *different key*, encrypting data that nothing could later decrypt.

It survived review because it reads as obviously reasonable, and it survived
testing because the test that exercised it only failed 4.7% of the time. Neither
a human nor a probabilistic test is the right defence. A grep is.

The rule: a value that came from `read_bytes()`, `b64decode()`, `urandom()` or a
`bytes(...)` literal may be hashed, sliced, compared and length-checked. It may
not be `strip`ped, `split`, `title`d or otherwise put through a method that
exists to tidy up human-typed text.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES = sorted((ROOT / "src" / "samvedna").rglob("*.py")) + sorted(
    (ROOT / "tools").glob("*.py")
)

# Calls that hand back raw bytes.
BINARY_SOURCES = frozenset(
    {
        "read_bytes",
        "b64decode",
        "urandom",
        "tobytes",
        "getrandbits",
        "digest",
    }
)

# Methods that exist to tidy human-typed text. `bytes` has all of them, which
# is why this mistake type-checks.
TEXT_ONLY_METHODS = frozenset(
    {
        "strip",
        "lstrip",
        "rstrip",
        "splitlines",
        "title",
        "capitalize",
        "casefold",
        "lower",
        "upper",
        "swapcase",
        "expandtabs",
    }
)


def _binary_text_calls(tree: ast.AST) -> list[tuple[int, str, str]]:
    """Find `<binary source>(...).<text method>(...)` in one chain."""
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        # We want a call whose function is an attribute access on another call.
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        if method not in TEXT_ONLY_METHODS:
            continue
        inner = node.func.value
        if not isinstance(inner, ast.Call):
            continue
        if not isinstance(inner.func, ast.Attribute):
            continue
        source = inner.func.attr
        if source in BINARY_SOURCES:
            found.append((node.lineno, source, method))
    return found


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_text_operations_on_binary_data(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    strays = _binary_text_calls(tree)
    assert not strays, (
        f"{path.relative_to(ROOT)} applies a text method to binary data: "
        + ", ".join(f"line {ln}: .{src}().{meth}()" for ln, src, meth in strays)
        + ". bytes has these methods and they corrupt key material — see this "
        "test's docstring."
    )


def test_the_guard_actually_catches_the_bug_that_shipped() -> None:
    """A guard nobody has seen fail is a guard nobody should trust.

    This is the exact line that was in `db/keys.py`.
    """
    tree = ast.parse("key = path.read_bytes().strip()\n")
    assert _binary_text_calls(tree) == [(1, "read_bytes", "strip")]


def test_the_guard_permits_the_legitimate_uses() -> None:
    """Hashing, slicing and comparing raw bytes are all fine.

    A guard that fires on correct code gets switched off, so the permitted
    cases are pinned as tightly as the forbidden ones.
    """
    allowed = (
        "digest = hashlib.sha256(path.read_bytes()).hexdigest()",   # tabular.py
        "if len(path.read_bytes()) != 32: raise Error",
        "head = path.read_bytes()[:8]",
        "same = path.read_bytes() == expected",
        # Stripping *text* is not what this test is about.
        "name = handle.read().strip()",
        "line = record.get('value', '').strip()",
    )
    for snippet in allowed:
        assert _binary_text_calls(ast.parse(snippet)) == [], snippet
