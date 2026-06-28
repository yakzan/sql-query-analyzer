"""Load SQL files and parse them with sqlglot, resilient to bad input."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.tokens import TokenType, Tokenizer

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


def _split_statements(raw: str) -> list[str]:
    try:
        tokens = Tokenizer().tokenize(raw)
    except Exception:  # noqa: BLE001 - tolerate tokenizer failures
        chunk = raw.strip()
        return [chunk] if chunk else []

    statements: list[str] = []
    start = 0
    for token in tokens:
        if token.token_type is TokenType.SEMICOLON:
            chunk = raw[start:token.start].strip()
            if chunk:
                statements.append(chunk)
            start = token.end + 1

    tail = raw[start:].strip()
    if tail:
        statements.append(tail)
    return statements


def parse_file(path: Path) -> list[ParsedStatement]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    rel = str(path)

    statements = _split_statements(raw)
    out: list[ParsedStatement] = []
    for i, statement in enumerate(statements):
        try:
            expr = sqlglot.parse_one(statement, read=PRIMARY_DIALECT)
            out.append(ParsedStatement(rel, i, PRIMARY_DIALECT, expr))
            continue
        except Exception as primary_exc:  # noqa: BLE001
            primary_err = f"{type(primary_exc).__name__}: {primary_exc}"

        try:
            expr = sqlglot.parse_one(statement, read=FALLBACK_DIALECT)
            out.append(ParsedStatement(rel, i, FALLBACK_DIALECT, expr))
        except Exception:  # noqa: BLE001
            out.append(ParsedStatement(rel, i, PRIMARY_DIALECT, None, primary_err))

    return out


def parse_all(root: str | Path) -> list[ParsedStatement]:
    statements: list[ParsedStatement] = []
    for path in load_sql_files(root):
        statements.extend(parse_file(path))
    return statements
