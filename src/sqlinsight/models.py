"""Shared data structures for the analysis pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ColumnRef:
    table: str | None  # resolved physical table, or None
    name: str
    status: str  # resolved | unqualified_resolved | derived | ambiguous
    context: str  # select | join | filter | group | aggregate


@dataclass
class JoinEdge:
    left_table: str
    right_table: str
    left_col: str
    right_col: str

    def canonical(self) -> tuple[str, str, str, str]:
        a = (self.left_table, self.left_col)
        b = (self.right_table, self.right_col)
        lo, hi = sorted([a, b])
        return (lo[0], hi[0], lo[1], hi[1])


@dataclass
class CteInfo:
    name: str
    file: str
    stmt_index: int
    tables: list[str]
    output_columns: list[str]
    normalized_sql: str
    exact_hash: str
    signature: str


@dataclass
class QueryRecord:
    file: str
    stmt_index: int
    parse_ok: bool
    dialect: str = ""
    error: str = ""
    kind: str = "select"  # select | insert_select | ctas | skipped_ddl
    target_table: str = ""  # write target for insert_select / ctas
    tables: list[str] = field(default_factory=list)
    columns: list[ColumnRef] = field(default_factory=list)
    joins: list[JoinEdge] = field(default_factory=list)
    group_columns: list[ColumnRef] = field(default_factory=list)
    aggregations: list[str] = field(default_factory=list)
    ctes: list[CteInfo] = field(default_factory=list)
