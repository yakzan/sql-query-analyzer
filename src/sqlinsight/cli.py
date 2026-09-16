"""Command-line orchestration for the sqlinsight pipeline."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import catalog, cooccurrence, graph, overlap, report
from .extract import extract_all
from .parse import parse_all


def run(
    source: str,
    outdir: str,
    catalog_path: str | None = None,
    resolution: float = 1.0,
    graph_edges: int = 200,
) -> int:
    src_path = Path(source)
    if not src_path.exists():
        print(f"error: source path not found: {source}", file=sys.stderr)
        return 1

    provided = None
    if catalog_path:
        try:
            provided = catalog.load_provided(catalog_path)
        except (OSError, ValueError) as exc:
            print(f"error: cannot load catalog {catalog_path}: {exc}", file=sys.stderr)
            return 1

    print(f"[1/6] parsing SQL under {source} ...")
    statements = parse_all(src_path)
    print(f"      {len(statements)} statement(s)")

    print("[2/6] extracting inventory ...")
    records = extract_all(statements)

    print("[3/6] inferring catalog + resolving ambiguous columns ...")
    cat = catalog.build_catalog(records)
    star_tables = None
    catalog_source = "inferred"
    if provided is not None:
        cat = catalog.merge(cat, provided)
        star_tables = set(provided)
        catalog_source = f"provided ({len(provided)} tables) + inferred"
    refine_stats = catalog.refine(records, cat, statements, star_tables=star_tables)
    refine_stats["catalog_source"] = catalog_source
    print(f"      catalog: {catalog_source}")
    print(f"      catalog-resolved {refine_stats['catalog_resolved']} column(s); "
          f"{refine_stats['still_ambiguous']} still ambiguous")

    print("[4/6] computing co-occurrence + overlap ...")
    table_freq = cooccurrence.table_frequency(records)
    table_cooc = cooccurrence.table_cooccurrence(records)
    col_cooc = cooccurrence.column_cooccurrence(records)
    join_rows = cooccurrence.join_edges(records)
    join_rels = cooccurrence.join_relationships(records)
    cooc_files = cooccurrence.cooccurring_file_counts(records)
    inferred_pairs = cooccurrence.partner_inferred_pairs(records)
    repeated = overlap.repeated_logic(records)

    print("[5/6] building graph + detecting clusters ...")
    all_tables = sorted({t for r in records for t in r.tables})
    g = graph.build_graph(
        all_tables, table_cooc, join_rels, cooc_files, inferred_pairs
    )
    communities = graph.detect_communities(g, resolution=resolution)
    clusters = graph.build_clusters(records, communities, join_rows)
    print(f"      {len(communities)} cluster(s) over {len(all_tables)} table(s)")

    print(f"[6/6] writing outputs to {outdir} ...")
    report.write_report(
        Path(outdir), src_path.name, records, refine_stats, table_freq, table_cooc,
        col_cooc, join_rows, repeated, clusters, g, communities,
        max_graph_edges=graph_edges,
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
    parser.add_argument(
        "--catalog",
        help="optional JSON file with the real schema catalog:"
             ' {"schema.table": ["col", ...]}. Wins over the inferred catalog'
             " per table and enables SELECT * expansion.",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=1.0,
        help="community detection resolution; > 1.0 favors more, smaller"
             " clusters (default 1.0)",
    )
    parser.add_argument(
        "--graph-edges",
        type=int,
        default=200,
        help="cap graph.html to the top-K join edges by frequency; the full"
             " set is always in join_edges.csv (default 200)",
    )
    args = parser.parse_args(argv)
    return run(
        args.source,
        args.out,
        catalog_path=args.catalog,
        resolution=args.resolution,
        graph_edges=args.graph_edges,
    )


if __name__ == "__main__":
    raise SystemExit(main())
