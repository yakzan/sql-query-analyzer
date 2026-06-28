"""Shared test helpers: turn raw SQL strings into QueryRecords."""
from __future__ import annotations

import sqlglot

from sqlinsight.extract import extract_record
from sqlinsight.models import QueryRecord
from sqlinsight.parse import PRIMARY_DIALECT, ParsedStatement


def record_for(sql: str, file: str = "t.sql", idx: int = 0) -> QueryRecord:
    expr = sqlglot.parse_one(sql, read=PRIMARY_DIALECT)
    stmt = ParsedStatement(file, idx, PRIMARY_DIALECT, expr)
    return extract_record(stmt)


def records_for(*sqls: str) -> list[QueryRecord]:
    return [record_for(s, file=f"q{i}.sql", idx=i) for i, s in enumerate(sqls)]
