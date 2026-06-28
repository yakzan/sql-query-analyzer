import networkx as nx

from sqlinsight.models import QueryRecord
from sqlinsight.report import write_report


def test_report_html_escapes_user_content(tmp_path):
    write_report(
        outdir=tmp_path,
        source="<script>alert(1)</script>",
        records=[QueryRecord(file="q.sql", stmt_index=0, parse_ok=True)],
        refine_stats={"catalog_resolved": 0, "still_ambiguous": 0},
        table_freq=[],
        table_cooc=[],
        col_cooc=[],
        join_rows=[],
        repeated=[],
        clusters=[],
        g=nx.Graph(),
        communities=[],
    )
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "Source: &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Source: <script>alert(1)</script>" not in html
