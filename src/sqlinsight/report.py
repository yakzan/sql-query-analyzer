"""Write CSVs, an inventory SQLite DB, an HTML report, and an interactive graph."""
from __future__ import annotations

import csv
import re
import sqlite3
from collections import Counter
from pathlib import Path

import networkx as nx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pyvis.network import Network

from .catalog import RESOLVED_STATUSES
from .models import QueryRecord

TEMPLATE_DIR = Path(__file__).parent / "templates"

_PALETTE = [
    "#2563eb", "#16a34a", "#dc2626", "#d97706", "#7c3aed",
    "#0891b2", "#db2777", "#65a30d", "#475569", "#ca8a04",
]

_STAT_COLUMN_TYPES = {
    "table_frequency": {"n_queries": "INTEGER"},
    "table_cooccurrence": {"count": "INTEGER"},
    "column_cooccurrence": {"count": "INTEGER"},
    "join_edges": {"count": "INTEGER"},
    "repeated_logic": {
        "occurrences": "INTEGER",
        "distinct_files": "INTEGER",
        "similarity": "REAL",
    },
    "clusters": {"cluster_id": "INTEGER", "size": "INTEGER"},
}


def _write_csv(path: Path, header: list[str], rows: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(list(r) if not isinstance(r, dict) else [r[h] for h in header])


def _write_sqlite(path: Path, records: list[QueryRecord], stat_tables: dict) -> None:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("CREATE TABLE schema_info(version INTEGER NOT NULL)")
    cur.execute("INSERT INTO schema_info VALUES(1)")
    cur.execute(
        "CREATE TABLE queries(file TEXT, stmt_index INT, parse_ok INT, dialect TEXT,"
        " error TEXT, kind TEXT, target_table TEXT, n_tables INT, n_joins INT,"
        " n_ctes INT, PRIMARY KEY(file, stmt_index))"
    )
    cur.execute("CREATE TABLE query_tables(file TEXT, stmt_index INT, table_name TEXT)")
    cur.execute(
        "CREATE TABLE columns(file TEXT, stmt_index INT, table_name TEXT, column_name"
        " TEXT, status TEXT, context TEXT)"
    )
    cur.execute(
        "CREATE TABLE joins(file TEXT, stmt_index INT, left_table TEXT, right_table TEXT,"
        " left_col TEXT, right_col TEXT, inference TEXT)"
    )
    cur.execute(
        "CREATE TABLE logic_units(name TEXT, file TEXT, stmt_index INT,"
        " unit_type TEXT, tables TEXT, output_columns TEXT, exact_hash TEXT,"
        " signature TEXT)"
    )
    for rec in records:
        cur.execute(
            "INSERT INTO queries VALUES(?,?,?,?,?,?,?,?,?,?)",
            (rec.file, rec.stmt_index, int(rec.parse_ok), rec.dialect, rec.error,
             rec.kind, rec.target_table, len(rec.tables), len(rec.joins),
             len(rec.ctes)),
        )
        cur.executemany(
            "INSERT INTO query_tables VALUES(?,?,?)",
            [(rec.file, rec.stmt_index, t) for t in rec.tables],
        )
        cur.executemany(
            "INSERT INTO columns VALUES(?,?,?,?,?,?)",
            [(rec.file, rec.stmt_index, c.table, c.name, c.status, c.context)
             for c in rec.columns],
        )
        cur.executemany(
            "INSERT INTO joins VALUES(?,?,?,?,?,?,?)",
            [(rec.file, rec.stmt_index, j.left_table, j.right_table, j.left_col,
              j.right_col, j.inference)
             for j in rec.joins],
        )
        cur.executemany(
            "INSERT INTO logic_units VALUES(?,?,?,?,?,?,?,?)",
            [(c.name, c.file, c.stmt_index, c.unit_type, ", ".join(c.tables),
              ", ".join(c.output_columns), c.exact_hash, c.signature)
             for c in (*rec.ctes, *rec.subqueries)],
        )
    for name, (header, rows) in stat_tables.items():
        types = _STAT_COLUMN_TYPES.get(name, {})
        cols = ", ".join(f'"{h}" {types.get(h, "TEXT")}' for h in header)
        cur.execute(f'CREATE TABLE "{name}"({cols})')
        placeholders = ",".join("?" * len(header))
        cur.executemany(
            f'INSERT INTO "{name}" VALUES({placeholders})',
            [tuple(r[h] if isinstance(r, dict) else r[i] for i, h in enumerate(header))
             for r in rows],
        )
    cur.execute("CREATE INDEX idx_query_tables_table ON query_tables(table_name)")
    cur.execute("CREATE INDEX idx_columns_table_column ON columns(table_name, column_name)")
    cur.execute("CREATE INDEX idx_joins_tables ON joins(left_table, right_table)")
    cur.execute("CREATE INDEX idx_logic_units_hash ON logic_units(exact_hash)")
    con.commit()
    con.close()


def _graph_html(
    path: Path, g: nx.Graph, communities: list[list[str]], max_edges: int = 200
) -> None:
    color_of: dict[str, str] = {}
    for i, members in enumerate(communities):
        for m in members:
            color_of[m] = _PALETTE[i % len(_PALETTE)]

    # Only draw join edges (real relationships); the full co-occurrence graph
    # connects every table pair in a query and produces an unreadable hairball.
    join_edges_only = sorted(
        ((a, b, data) for a, b, data in g.edges(data=True) if data.get("joins", 0) > 0),
        key=lambda e: (-e[2].get("joins", 0), e[0], e[1]),
    )
    total_join_edges = len(join_edges_only)
    join_edges_only = join_edges_only[:max_edges]
    truncation_note = (
        f"Showing top {len(join_edges_only)} of {total_join_edges} join edges "
        f"by frequency; see join_edges.csv for the full set."
        if total_join_edges > len(join_edges_only)
        else ""
    )
    join_degree: dict[str, int] = {n: 0 for n in g.nodes()}
    for a, b, _ in join_edges_only:
        join_degree[a] += 1
        join_degree[b] += 1

    net = Network(height="760px", width="100%", bgcolor="#ffffff",
                  font_color="#1b2733", cdn_resources="in_line", notebook=False)
    net.set_options("""
    {
      "nodes": {"shape": "dot", "font": {"size": 16, "face": "sans-serif", "strokeWidth": 3, "strokeColor": "#ffffff"}},
      "edges": {"color": {"color": "#94a3b8", "highlight": "#2563eb"}, "smooth": {"type": "continuous"}},
      "physics": {"barnesHut": {"gravitationalConstant": -12000, "springLength": 180, "springConstant": 0.03, "damping": 0.4}, "minVelocity": 0.75, "stabilization": {"enabled": true, "iterations": 400, "fit": true}},
      "interaction": {"hover": true, "tooltipDelay": 80}
    }
    """)
    for node in g.nodes():
        deg = join_degree.get(node, 0)
        net.add_node(node, label=node, color=color_of.get(node, "#94a3b8"),
                     size=12 + 4 * deg, title=f"{node} - {deg} join relationship(s)")
    for a, b, data in join_edges_only:
        n = data.get("joins", 0)
        inferred = data.get("inferred", False)
        net.add_edge(
            a, b, value=n, width=1 + n, dashes=inferred,
            title=f"{n} join(s)" + (" (partner-inferred)" if inferred else ""),
        )

    net.write_html(str(path), notebook=False, open_browser=False)
    _inject_legend(path, communities, truncation_note)


def _inject_legend(
    path: Path, communities: list[list[str]], truncation_note: str = ""
) -> None:
    items = []
    for i, members in enumerate(communities):
        color = _PALETTE[i % len(_PALETTE)]
        items.append(
            f'<div style="display:flex;align-items:center;gap:6px;margin:2px 0">'
            f'<span style="width:12px;height:12px;border-radius:50%;background:{color};'
            f'display:inline-block"></span>Cluster {i} ({len(members)} tables)</div>'
        )
    note = (
        f'<div style="color:#b45309;margin-top:6px">{truncation_note}</div>'
        if truncation_note
        else ""
    )
    legend = (
        '<div style="position:fixed;top:12px;right:12px;z-index:999;background:#fff;'
        'border:1px solid #dfe6ee;border-radius:10px;padding:12px 14px;'
        'font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:12px;'
        'box-shadow:0 2px 8px rgba(0,0,0,.12);max-width:260px">'
        '<div style="font-weight:700;margin-bottom:6px">Cluster legend</div>'
        + "".join(items)
        + '<div style="color:#5b6b7b;margin-top:8px;border-top:1px solid #eef2f6;'
        'padding-top:6px">Edges = join relationships (dashed = partner-inferred). '
        'Node size = number of joins. Hover for details.</div>'
        + note
        + "</div>"
    )
    html = path.read_text(encoding="utf-8")
    # Pyvis includes Bootstrap CDN tags even in in_line mode; this graph uses
    # neither its menus nor Bootstrap widgets.
    html = re.sub(
        r'<link\b[^>]*href="https://cdn\.jsdelivr\.net/npm/bootstrap@[^>]*>',
        "", html,
    )
    html = re.sub(
        r'<script\b[^>]*src="https://cdn\.jsdelivr\.net/npm/bootstrap@[^>]*>\s*</script>',
        "", html,
    )
    html = html.replace("</body>", legend + "\n</body>", 1)
    path.write_text(html, encoding="utf-8")


def _table_section(title, hint, columns, rows, limit=300, sql_cols=()):
    trimmed = [
        [r[h] if isinstance(r, dict) else r[i] for i, h in enumerate(columns)]
        for r in rows[:limit]
    ]
    return {"title": title, "hint": hint, "columns": columns, "rows": trimmed,
            "sql_cols": set(sql_cols)}


def write_report(
    outdir: Path,
    source: str,
    records: list[QueryRecord],
    refine_stats: dict,
    table_freq,
    table_cooc,
    col_cooc,
    join_rows,
    repeated,
    clusters,
    g: nx.Graph,
    communities: list[list[str]],
    max_graph_edges: int = 200,
) -> None:
    outdir.mkdir(parents=True, exist_ok=True)

    csv_specs = {
        "table_frequency.csv": (["table", "n_queries"], table_freq),
        "table_cooccurrence.csv": (["table_a", "table_b", "count"], table_cooc),
        "column_cooccurrence.csv": (["column_a", "column_b", "count"], col_cooc),
        "join_edges.csv": (
            ["left_table", "right_table", "left_col", "right_col", "count",
             "inference"], join_rows),
        "repeated_logic.csv": (
            ["match_type", "key", "occurrences", "distinct_files", "similarity",
             "unit_types", "unit_names", "files", "tables", "sample_sql"], repeated),
        "clusters.csv": (
            ["cluster_id", "size", "tables", "internal_join_keys",
             "supporting_files", "repeated_ctes", "note"], clusters),
    }
    for fname, (header, rows) in csv_specs.items():
        _write_csv(outdir / fname, header, rows)

    stat_tables = {fname[:-4]: (header, rows) for fname, (header, rows) in csv_specs.items()}
    _write_sqlite(outdir / "inventory.sqlite", records, stat_tables)

    errors = [r for r in records if r.error]
    (outdir / "parse_errors.log").write_text(
        "\n".join(f"{r.file}#{r.stmt_index}\t{r.error}" for r in errors) or "none\n",
        encoding="utf-8",
    )

    _graph_html(outdir / "graph.html", g, communities, max_edges=max_graph_edges)

    parsed_ok = sum(1 for r in records if r.parse_ok)
    total = len(records) or 1
    all_cols = [c for r in records for c in r.columns]
    resolved = sum(1 for c in all_cols if c.status in RESOLVED_STATUSES)
    ambiguous = sum(1 for c in all_cols if c.status == "ambiguous")
    distinct_tables = len({t for r in records for t in r.tables})

    kind_counts = sorted(Counter(r.kind for r in records if r.parse_ok).items())
    kinds_summary = ", ".join(f"{k}: {n}" for k, n in kind_counts) or "none"

    metrics = [
        ("SQL files", len({r.file for r in records})),
        ("Statements", len(records)),
        ("Statement kinds", kinds_summary),
        ("Catalog source", refine_stats.get("catalog_source", "inferred")),
        ("Parse coverage", f"{100 * parsed_ok / total:.0f}%"),
        ("Distinct tables", distinct_tables),
        ("Columns resolved", f"{100 * resolved / (len(all_cols) or 1):.0f}%"),
        ("Ambiguous cols", ambiguous),
        ("Clusters", len(communities)),
    ]

    sections = [
        _table_section("Cluster suggestions",
                        "Communities of join-coupled tables. A starting point for "
                        "grouping new dbt models, not a prescription.",
                        ["cluster_id", "size", "tables", "internal_join_keys",
                         "supporting_files", "repeated_ctes", "note"], clusters),
        _table_section("Repeated logic (overlap)",
                        "CTE/subquery blocks reused across files, ranked by "
                        "occurrences x similarity (consolidation ROI). 'exact' = "
                        "identical SQL; 'near_dupe' = token-level similar "
                        "(literals masked, blended shingle/token Jaccard).",
                        ["match_type", "key", "occurrences", "distinct_files",
                         "similarity", "unit_types", "unit_names", "files",
                         "tables", "sample_sql"], repeated,
                        sql_cols=("sample_sql",)),
        _table_section("Join edges",
                        "How often each table pair is joined, and on which keys. "
                        "'partner' = one side was ambiguous and inferred from its "
                        "resolved join partner (evidence-based, never silent).",
                        ["left_table", "right_table", "left_col", "right_col",
                         "count", "inference"],
                        join_rows),
        _table_section("Table co-occurrence",
                        "Table pairs appearing in the same query.",
                        ["table_a", "table_b", "count"], table_cooc),
        _table_section("Column co-occurrence",
                        "Co-occurring columns (join/filter/group context only).",
                        ["column_a", "column_b", "count"], col_cooc),
        _table_section("Table frequency",
                        "Most-referenced physical tables across the corpus.",
                        ["table", "n_queries"], table_freq),
    ]

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "html.j2"]),
    )
    html = env.get_template("report.html.j2").render(
        source=source, metrics=metrics, sections=sections,
    )
    (outdir / "report.html").write_text(html, encoding="utf-8")
