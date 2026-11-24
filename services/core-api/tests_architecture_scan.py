"""Import-boundary scanner shared by the architecture test and the eval harness.

Rule: no module under app/ai may import app.domain.quoting (directly or via a relative import),
and nothing outside the quoting router/service may construct quotes.
"""
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_FROM_AI = ("app.domain.quoting", "app.api.v1.submissions")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                pkg = ".".join(path.relative_to(path.parents[len(path.parts) - 1]).parts)  # pragma: no cover
                mod = f"relative:{node.level}:{mod}:{pkg}"
            out.append(mod)
            out.extend(f"{mod}.{a.name}" for a in node.names)
    return out


def scan_ai_imports(app_dir: Path) -> list[str]:
    violations = []
    for py in sorted((app_dir / "ai").rglob("*.py")):
        for imp in _imports(py):
            if imp.startswith("relative:") and "quoting" in imp:
                violations.append(f"{py.relative_to(app_dir)}: {imp}")
            if any(imp == f or imp.startswith(f + ".") for f in FORBIDDEN_FROM_AI) or ".quoting" in imp:
                violations.append(f"{py.relative_to(app_dir)}: {imp}")
    return violations


def scan_quote_constructors(app_dir: Path) -> list[str]:
    """`Quote(` may only be instantiated inside domain/quoting/service.py."""
    hits = []
    for py in sorted(app_dir.rglob("*.py")):
        rel = py.relative_to(app_dir).as_posix()
        if rel in ("domain/quoting/service.py", "models/__init__.py"):
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Quote":
                hits.append(f"{rel}:{node.lineno}")
    return hits
