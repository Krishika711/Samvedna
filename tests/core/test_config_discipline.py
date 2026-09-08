"""PART 4: no magic numbers outside `config/`.

This is checked mechanically rather than by review, because the discipline only
holds if breaking it is noisy. A threshold that drifts into `gates.py` is not a
style problem — it is a number a governance board never approved, sitting in the
path that decides whether a jawan is named.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
DECISION_LAYER = ROOT / "src" / "samvedna" / "core"

# Numbers with no policy content: identity, counts, array indices, unit bounds.
ALLOWED = {0, 1, 2, 3, -1, 100, 1000}


def numeric_literals(path: Path) -> list[tuple[int, float]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            if isinstance(node.value, bool):
                continue
            if node.value in ALLOWED:
                continue
            out.append((node.lineno, node.value))
    return out


@pytest.mark.parametrize(
    "path", sorted(DECISION_LAYER.glob("*.py")), ids=lambda p: p.name
)
def test_no_policy_numbers_in_the_decision_layer(path):
    """Every threshold, weight and mass in L3 must be imported from config."""
    strays = numeric_literals(path)
    # Rounding precision for display is not a policy number.
    strays = [(ln, v) for ln, v in strays if v not in (4, 1e-12, 5e-4)]
    assert not strays, (
        f"{path.name} contains numeric literals that belong in config/: {strays}"
    )


def test_every_gate_threshold_is_configured():
    from samvedna.config.thresholds import GATE_THRESHOLDS
    from samvedna.core.gates import GATE_ORDER

    assert set(GATE_THRESHOLDS) == set(GATE_ORDER)


def test_every_confounder_rule_has_a_mass_and_a_label():
    from samvedna.config.thresholds import CONFOUNDER_LABEL, CONFOUNDER_MASS
    from samvedna.core.confounders import RULES

    assert len(RULES) == len(CONFOUNDER_MASS) == len(CONFOUNDER_LABEL)
    assert set(CONFOUNDER_MASS) == set(CONFOUNDER_LABEL)


def test_the_decision_layer_performs_no_io():
    """L3 must not import a database, a network client, a clock source or a model."""
    banned = {
        "sqlalchemy", "httpx", "requests", "aiosqlite", "torch", "lightgbm",
        "shap", "numpy", "asyncio", "fastapi", "time", "random", "os", "logging",
    }
    for path in DECISION_LAYER.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                assert name not in banned, f"{path.name} imports {name}; L3 must stay pure"


def test_the_decision_layer_never_imports_a_layer_below_it():
    for path in DECISION_LAYER.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            if module and module.startswith("samvedna."):
                head = module.split(".")[1]
                assert head in ("core", "config"), (
                    f"{path.name} imports samvedna.{head}; L3 depends downward only"
                )
