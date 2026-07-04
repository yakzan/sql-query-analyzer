"""Bootstrap an inferred table->columns catalog from the corpus and use it
to resolve some columns that scope analysis left ambiguous. A real catalog
(--catalog, from the warehouse) can be provided; it wins per table and also
unlocks SELECT * expansion, with inference kept as the offline fallback."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .extract import extract_record
from .models import QueryRecord
from .parse import ParsedStatement

RESOLVED_STATUSES = {
    "resolved", "unqualified_resolved", "catalog_resolved", "star_expanded",
}


def load_provided(path: str | Path) -> dict[str, set[str]]:
    """Load a provided catalog JSON: {"schema.table": ["col", ...], ...}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("catalog file must be a JSON object of table -> [columns]")
    catalog: dict[str, set[str]] = {}
    for table, cols in data.items():
        if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
            raise ValueError(
                f"invalid catalog entry for {table!r}: expected a list of column names"
            )
        catalog[table.lower()] = {c.lower() for c in cols}
    return catalog


def merge(
    inferred: dict[str, set[str]], provided: dict[str, set[str]]
) -> dict[str, set[str]]:
    """Provided catalog wins per table; inferred fills the gaps."""
    merged = dict(inferred)
    merged.update(provided)
    return merged


def build_catalog(records: list[QueryRecord]) -> dict[str, set[str]]:
    catalog: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        for col in rec.columns:
            if col.table and col.status in {"resolved", "unqualified_resolved"}:
                catalog[col.table].add(col.name.lower())
    return dict(catalog)


def refine(
    records: list[QueryRecord],
    catalog: dict[str, set[str]],
    statements: list[ParsedStatement] | None = None,
    star_tables: set[str] | None = None,
) -> dict[str, int]:
    """Second pass: attribute ambiguous columns when the catalog points to
    exactly one candidate table present in the same query. star_tables (tables
    backed by a provided, trusted catalog) additionally get SELECT * expansion."""
    stats = {"catalog_resolved": 0, "still_ambiguous": 0}
    if statements is not None:
        by_key = {(s.file, s.stmt_index): s for s in statements}
        for i, rec in enumerate(records):
            stmt = by_key.get((rec.file, rec.stmt_index))
            if stmt is None:
                continue
            updated = extract_record(stmt, catalog=catalog, star_tables=star_tables)
            records[i] = updated
            for col in updated.columns:
                if col.status == "catalog_resolved":
                    stats["catalog_resolved"] += 1
                elif col.status == "ambiguous":
                    stats["still_ambiguous"] += 1
        return stats

    for rec in records:
        for col in rec.columns:
            if col.status != "ambiguous":
                continue
            candidates = [
                t for t in rec.tables if col.name.lower() in catalog.get(t, set())
            ]
            if len(candidates) == 1:
                col.table = candidates[0]
                col.status = "catalog_resolved"
                stats["catalog_resolved"] += 1
            else:
                stats["still_ambiguous"] += 1
    return stats
