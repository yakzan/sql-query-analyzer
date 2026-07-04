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


def cooccurring_file_counts(
    records: list[QueryRecord],
) -> dict[tuple[str, str], int]:
    """Distinct files in which each table pair co-occurs. Pairs seen in a
    single file only (e.g. one wide dashboard query) are weak evidence."""
    files: dict[tuple[str, str], set[str]] = {}
    for rec in records:
        for a, b in combinations(sorted(set(rec.tables)), 2):
            files.setdefault((a, b), set()).add(rec.file)
    return {pair: len(fs) for pair, fs in files.items()}


def join_relationships(records: list[QueryRecord]) -> list[tuple[str, str, int]]:
    """Join relationships per table pair: composite keys collapse to one
    relationship per pair per statement, so a two-column key does not count
    double. Key-column detail stays in join_edges()."""
    counter: Counter[tuple[str, str]] = Counter()
    for rec in records:
        pairs = {tuple(sorted((j.left_table, j.right_table))) for j in rec.joins}
        for pair in pairs:
            counter[pair] += 1
    return sorted(
        ((a, b, n) for (a, b), n in counter.items()),
        key=lambda r: (-r[2], r[0], r[1]),
    )


def join_edges(
    records: list[QueryRecord],
) -> list[tuple[str, str, str, str, int, str]]:
    counter: Counter[tuple[str, str, str, str, str]] = Counter()
    for rec in records:
        for j in rec.joins:
            counter[j.canonical() + (j.inference,)] += 1
    return sorted(
        ((lt, rt, lc, rc, n, inf) for (lt, rt, lc, rc, inf), n in counter.items()),
        key=lambda r: (-r[4], r[0], r[1], r[2], r[3], r[5]),
    )


def partner_inferred_pairs(records: list[QueryRecord]) -> set[tuple[str, str]]:
    """Table pairs whose every observed join was partner-inferred; rendered
    distinctly so inferred structure is never mistaken for stated structure."""
    inferences: dict[tuple[str, str], set[str]] = {}
    for rec in records:
        for j in rec.joins:
            pair = tuple(sorted((j.left_table, j.right_table)))
            inferences.setdefault(pair, set()).add(j.inference)
    return {pair for pair, infs in inferences.items() if infs == {"partner"}}
