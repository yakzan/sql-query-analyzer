import networkx as nx
from html.parser import HTMLParser

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


def test_graph_html_caps_edges_with_note(tmp_path):
    g = nx.Graph()
    g.add_edge("a", "b", weight=3.0, joins=3)
    g.add_edge("b", "c", weight=1.0, joins=1)
    write_report(
        outdir=tmp_path,
        source="src",
        records=[],
        refine_stats={"catalog_resolved": 0, "still_ambiguous": 0},
        table_freq=[],
        table_cooc=[],
        col_cooc=[],
        join_rows=[],
        repeated=[],
        clusters=[],
        g=g,
        communities=[["a", "b", "c"]],
        max_graph_edges=1,
    )
    html = (tmp_path / "graph.html").read_text(encoding="utf-8")
    assert "Showing top 1 of 2 join edges" in html
    assert '"from": "a"' in html
    assert '"to": "c"' not in html


def test_graph_html_escapes_script_terminators_and_is_offline(tmp_path):
    payload = "</script><script>alert('graph-xss')</script>"
    g = nx.Graph()
    g.add_node(payload)
    write_report(
        outdir=tmp_path,
        source="src",
        records=[],
        refine_stats={"catalog_resolved": 0, "still_ambiguous": 0},
        table_freq=[],
        table_cooc=[],
        col_cooc=[],
        join_rows=[],
        repeated=[],
        clusters=[],
        g=g,
        communities=[[payload]],
    )

    html = (tmp_path / "graph.html").read_text(encoding="utf-8")
    assert payload not in html
    resources = []

    class ResourceParser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag in {"script", "link"}:
                resources.extend(attributes[a] for a in ("src", "href") if a in attributes)

    ResourceParser().feed(html)
    assert resources == []
