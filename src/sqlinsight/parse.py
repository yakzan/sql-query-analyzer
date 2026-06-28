"""Load SQL files and parse them with sqlglot, resilient to bad input."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import sqlglot
from sqlglot import exp

PRIMARY_DIALECT = "redshift"
FALLBACK_DIALECT = "postgres"


@dataclass
class ParsedStatement:
    file: str
    stmt_index: int
    dialect: str
    expression: exp.Expression | None
    error: str = ""


def load_sql_files(root: str | Path) -> list[Path]:
    root = Path(root)
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*.sql") if p.is_file())


def _parse_with(sql: str, dialect: str) -> list[exp.Expression]:
    return [e for e in sqlglot.parse(sql, read=dialect) if e is not None]


def parse_file(path: Path) -> list[ParsedStatement]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    rel = str(path)
    for dialect in (PRIMARY_DIALECT, FALLBACK_DIALECT):
        try:
            expressions = _parse_with(raw, dialect)
        except Exception:  # noqa: BLE001 - sqlglot raises various parse errors
            continue
        return [
            ParsedStatement(rel, i, dialect, e)
            for i, e in enumerate(expressions)
        ]
    # Both dialects failed: record one failing statement with the error message.
    try:
        _parse_with(raw, PRIMARY_DIALECT)
        err = "unknown parse failure"
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    return [ParsedStatement(rel, 0, PRIMARY_DIALECT, None, err)]


def parse_all(root: str | Path) -> list[ParsedStatement]:
    statements: list[ParsedStatement] = []
    for path in load_sql_files(root):
        statements.extend(parse_file(path))
    return statements
