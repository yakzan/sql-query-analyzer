"""Bootstrap an inferred table->columns catalog from the corpus and use it
to resolve some columns that scope analysis left ambiguous."""
from __future__ import annotations

from collections import defaultdict

from .extract import extract_record
from .models import QueryRecord
from .parse import ParsedStatement

RESOLVED_STATUSES = {"resolved", "unqualified_resolved", "catalog_resolved"}


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
) -> dict[str, int]:
    """Second pass: attribute ambiguous columns when the inferred catalog
    points to exactly one candidate table present in the same query."""
    stats = {"catalog_resolved": 0, "still_ambiguous": 0}
    if statements is not None:
        by_key = {(s.file, s.stmt_index): s for s in statements}
        for i, rec in enumerate(records):
            stmt = by_key.get((rec.file, rec.stmt_index))
            if stmt is None:
                continue
            updated = extract_record(stmt, catalog=catalog)
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
