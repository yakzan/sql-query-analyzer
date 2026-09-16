"""Load SQL files and parse them with sqlglot, resilient to bad input."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.tokens import TokenType, Tokenizer

PRIMARY_DIALECT = "redshift"
FALLBACK_DIALECT = "postgres"

_DBT_REF = re.compile(
    r"\{\{\s*ref\(\s*(['\"])([A-Za-z_][\w$]*)\1"
    r"(?:\s*,\s*(['\"])([A-Za-z_][\w$]*)\3)?\s*\)\s*\}\}",
    re.IGNORECASE,
)
_DBT_SOURCE = re.compile(
    r"\{\{\s*source\(\s*(['\"])([A-Za-z_][\w$]*)\1\s*,\s*"
    r"(['\"])([A-Za-z_][\w$]*)\3\s*\)\s*\}\}",
    re.IGNORECASE,
)
_DBT_CONFIG = re.compile(r"\{\{\s*config\(.*?\)\s*\}\}", re.IGNORECASE | re.DOTALL)
_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)


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


def _replace_dbt_relations(raw: str) -> str:
    """Resolve static dbt relation macros without evaluating arbitrary Jinja."""
    raw = _JINJA_COMMENT.sub("", raw)
    raw = _DBT_CONFIG.sub("", raw)
    raw = _DBT_SOURCE.sub(lambda m: f"{m.group(2)}.{m.group(4)}", raw)
    return _DBT_REF.sub(
        lambda m: f"{m.group(2)}.{m.group(4)}" if m.group(4) else m.group(2), raw
    )


def _parse_error(exc: Exception) -> str:
    """Keep useful location data without persisting source excerpts or literals."""
    errors = getattr(exc, "errors", None)
    if errors:
        first = errors[0]
        line = first.get("line")
        col = first.get("col")
        if line is not None and col is not None:
            return f"{type(exc).__name__}: unable to parse SQL at line {line}, column {col}"
    return f"{type(exc).__name__}: unable to parse SQL"


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


def parse_file(path: Path, display_path: str | None = None) -> list[ParsedStatement]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = _replace_dbt_relations(raw)
    rel = display_path or str(path)

    statements = _split_statements(raw)
    out: list[ParsedStatement] = []
    for i, statement in enumerate(statements):
        try:
            expr = sqlglot.parse_one(statement, read=PRIMARY_DIALECT)
            out.append(ParsedStatement(rel, i, PRIMARY_DIALECT, expr))
            continue
        except Exception as primary_exc:  # noqa: BLE001
            primary_err = _parse_error(primary_exc)

        try:
            expr = sqlglot.parse_one(statement, read=FALLBACK_DIALECT)
            out.append(ParsedStatement(rel, i, FALLBACK_DIALECT, expr))
        except Exception:  # noqa: BLE001
            out.append(ParsedStatement(rel, i, PRIMARY_DIALECT, None, primary_err))

    return out


def parse_all(root: str | Path) -> list[ParsedStatement]:
    root = Path(root)
    statements: list[ParsedStatement] = []
    for path in load_sql_files(root):
        display_path = (
            path.name
            if root.is_file()
            else (Path(root.name) / path.relative_to(root)).as_posix()
        )
        statements.extend(parse_file(path, display_path=display_path))
    return statements
