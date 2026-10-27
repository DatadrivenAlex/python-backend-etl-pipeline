"""The domain and application layers do not import frameworks."""

from __future__ import annotations

import ast
from pathlib import Path

import etl_pipeline.application as application_pkg
import etl_pipeline.domain as domain_pkg

_FORBIDDEN_ROOTS = {
    "pandas",
    "sqlalchemy",
    "fastapi",
    "pydantic",
    "psycopg",
    "starlette",
    "uvicorn",
    "infrastructure",
    "api",
}


def test_domain_and_application_are_framework_free() -> None:
    roots = [
        Path(domain_pkg.__file__).resolve().parent,
        Path(application_pkg.__file__).resolve().parent,
    ]
    offenders: list[str] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for module in _imports(tree):
                root_name = module.split(".")[0]
                if root_name in _FORBIDDEN_ROOTS or module.startswith(
                    ("etl_pipeline.infrastructure", "etl_pipeline.api", "etl_pipeline.composition")
                ):
                    offenders.append(f"{path.name} imports {module}")
    assert offenders == []


def _imports(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found
