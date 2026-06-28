"""Command-line orchestration for the sqlinsight pipeline."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import catalog, cooccurrence, graph, overlap, report
from .extract import extract_all
from .parse import parse_all


def run(source: str, outdir: str) -> int:
    src_path = Path(source)
    if not src_path.exists():
        print(f"error: source path not found: {source}", file=sys.stderr)
        return 1

    print(f"[1/6] parsing SQL under {source} ...")
    statements = parse_all(src_path)
    print(f"      {len(statements)} statement(s)")

    print("[2/6] extracting inventory ...")
    records = extract_all(statements)

    print("[3/6] inferring catalog + resolving ambiguous columns ...")
    cat = catalog.build_catalog(records)
    refine_stats = catalog.refine(records, cat)
    print(f"      catalog-resolved {refine_stats['catalog_resolved']} column(s); "
          f"{refine_stats['still_ambiguous']} still ambiguous")

    print("[4/6] computing co-occurrence + overlap ...")
    table_freq = cooccurrence.table_frequency(records)
    table_cooc = cooccurrence.table_cooccurrence(records)
    col_cooc = cooccurrence.column_cooccurrence(records)
    join_rows = cooccurrence.join_edges(records)
    repeated = overlap.repeated_logic(records)

    print("[5/6] building graph + detecting clusters ...")
    all_tables = sorted({t for r in records for t in r.tables})
    g = graph.build_graph(all_tables, table_cooc, join_rows)
    communities = graph.detect_communities(g)
    clusters = graph.build_clusters(records, communities, join_rows)
    print(f"      {len(communities)} cluster(s) over {len(all_tables)} table(s)")

    print(f"[6/6] writing outputs to {outdir} ...")
    report.write_report(
        Path(outdir), source, records, refine_stats, table_freq, table_cooc,
        col_cooc, join_rows, repeated, clusters, g, communities,
    )
    print("done. open", str(Path(outdir) / "report.html"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sqlinsight",
        description="Deterministic co-occurrence & clustering analysis for raw SQL.",
    )
    parser.add_argument("source", help="directory or file containing .sql files")
    parser.add_argument("-o", "--out", default="output", help="output directory")
    args = parser.parse_args(argv)
    return run(args.source, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
