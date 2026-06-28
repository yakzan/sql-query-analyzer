"""Detect repeated logic blocks (CTEs/subqueries) across the corpus.

Two signals:
  - exact: identical normalized SQL (copy-paste reuse)
  - structural: same (tables, output columns) signature but differing SQL
    (near-duplicates worth consolidating into one model)
"""
from __future__ import annotations

from collections import defaultdict

from .models import CteInfo, QueryRecord


def collect_ctes(records: list[QueryRecord]) -> list[CteInfo]:
    ctes: list[CteInfo] = []
    for rec in records:
        ctes.extend(rec.ctes)
    return ctes


def _row(match_type: str, key: str, group: list[CteInfo]) -> dict:
    files = sorted({c.file for c in group})
    names = sorted({c.name for c in group})
    tables = sorted({t for c in group for t in c.tables})
    sample = group[0].normalized_sql
    if len(sample) > 600:
        sample = sample[:600] + " ..."
    return {
        "match_type": match_type,
        "key": key,
        "occurrences": len(group),
        "distinct_files": len(files),
        "cte_names": ", ".join(names),
        "files": ", ".join(files),
        "tables": ", ".join(tables),
        "sample_sql": sample,
    }


def repeated_logic(records: list[QueryRecord]) -> list[dict]:
    ctes = collect_ctes(records)

    by_hash: dict[str, list[CteInfo]] = defaultdict(list)
    by_sig: dict[str, list[CteInfo]] = defaultdict(list)
    for c in ctes:
        by_hash[c.exact_hash].append(c)
        by_sig[c.signature].append(c)

    rows: list[dict] = []
    for h, group in by_hash.items():
        if len(group) >= 2:
            rows.append(_row("exact", h[:12], group))

    for sig, group in by_sig.items():
        distinct_hashes = {c.exact_hash for c in group}
        if len(group) >= 2 and len(distinct_hashes) >= 2:
            rows.append(_row("structural", sig[:80], group))

    rows.sort(key=lambda r: (-r["occurrences"], r["match_type"], r["key"]))
    return rows
