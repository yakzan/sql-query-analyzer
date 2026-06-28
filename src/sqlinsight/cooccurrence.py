"""Deterministic co-occurrence statistics across the query corpus."""
from __future__ import annotations

from collections import Counter
from itertools import combinations

from .models import QueryRecord

INTERESTING_CONTEXTS = {"join", "filter", "group"}


def table_frequency(records: list[QueryRecord]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for rec in records:
        for t in set(rec.tables):
            counter[t] += 1
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))


def table_cooccurrence(records: list[QueryRecord]) -> list[tuple[str, str, int]]:
    counter: Counter[tuple[str, str]] = Counter()
    for rec in records:
        for a, b in combinations(sorted(set(rec.tables)), 2):
            counter[(a, b)] += 1
    return sorted(
        ((a, b, c) for (a, b), c in counter.items()),
        key=lambda r: (-r[2], r[0], r[1]),
    )


def _interesting_columns(rec: QueryRecord) -> set[str]:
    cols: set[str] = set()
    for col in rec.columns:
        if col.table and col.context in INTERESTING_CONTEXTS:
            cols.add(f"{col.table}.{col.name.lower()}")
    return cols


def column_cooccurrence(records: list[QueryRecord]) -> list[tuple[str, str, int]]:
    counter: Counter[tuple[str, str]] = Counter()
    for rec in records:
        for a, b in combinations(sorted(_interesting_columns(rec)), 2):
            counter[(a, b)] += 1
    return sorted(
        ((a, b, c) for (a, b), c in counter.items()),
        key=lambda r: (-r[2], r[0], r[1]),
    )


def join_edges(records: list[QueryRecord]) -> list[tuple[str, str, str, str, int]]:
    counter: Counter[tuple[str, str, str, str]] = Counter()
    for rec in records:
        for j in rec.joins:
            counter[j.canonical()] += 1
    return sorted(
        ((lt, rt, lc, rc, n) for (lt, rt, lc, rc), n in counter.items()),
        key=lambda r: (-r[4], r[0], r[1]),
    )
