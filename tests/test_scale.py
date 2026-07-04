"""Scale gate: full pipeline on a seeded ~80-file synthetic corpus with
planted ground truth. Run explicitly with: uv run pytest -m slow"""
from __future__ import annotations

import csv
import time
from pathlib import Path

import pytest

from gen_corpus import generate_corpus
from sqlinsight import cli

pytestmark = pytest.mark.slow

RUNTIME_BUDGET_S = 30
GRAPH_HTML_BUDGET = 3 * 1024 * 1024
MAX_COMMUNITY_SHARE = 0.6


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def scale_run(tmp_path_factory):
    base = tmp_path_factory.mktemp("scale")
    corpus = base / "corpus"
    truth = generate_corpus(corpus)
    out = base / "out"
    start = time.perf_counter()
    assert cli.run(str(corpus), str(out)) == 0
    elapsed = time.perf_counter() - start
    return truth, out, elapsed, corpus


def test_runtime_within_budget(scale_run):
    _, _, elapsed, _ = scale_run
    assert elapsed < RUNTIME_BUDGET_S, f"pipeline took {elapsed:.1f}s"


def test_full_parse_coverage(scale_run):
    truth, out, _, _ = scale_run
    assert (out / "parse_errors.log").read_text(encoding="utf-8").strip() == "none"


def test_planted_exact_duplicates_recalled(scale_run):
    truth, out, _, _ = scale_run
    rows = _rows(out / "repeated_logic.csv")
    exact = [
        r for r in rows
        if r["match_type"] == "exact" and r["unit_names"] == "shared_metrics"
    ]
    assert len(exact) == 1
    assert int(exact[0]["occurrences"]) == truth.exact_occurrences
    assert exact[0]["similarity"] == "1.00"


def test_planted_near_duplicates_recalled(scale_run):
    truth, out, _, _ = scale_run
    rows = _rows(out / "repeated_logic.csv")
    near = [r for r in rows if r["match_type"] == "near_dupe"]
    assert len(near) == 1
    assert int(near[0]["occurrences"]) == truth.near_occurrences


def test_composite_key_rows_present(scale_run):
    truth, out, _, _ = scale_run
    a, b = truth.composite_pair
    rows = [
        r for r in _rows(out / "join_edges.csv")
        if {r["left_table"], r["right_table"]} == {a, b}
    ]
    counts = {
        frozenset((r["left_col"], r["right_col"])): int(r["count"]) for r in rows
    }
    for key in truth.composite_keys:
        matching = [n for cols, n in counts.items() if key in cols]
        assert truth.composite_statements in matching, (
            f"composite key {key} missing expected count"
        )


def test_no_giant_community(scale_run):
    _, out, _, _ = scale_run
    joined = {
        t
        for r in _rows(out / "join_edges.csv")
        for t in (r["left_table"], r["right_table"])
    }
    sizes = [int(r["size"]) for r in _rows(out / "clusters.csv")]
    assert max(sizes) <= MAX_COMMUNITY_SHARE * len(joined), (
        f"largest community {max(sizes)} of {len(joined)} joined tables"
    )


def test_graph_html_within_budget(scale_run):
    _, out, _, _ = scale_run
    assert (out / "graph.html").stat().st_size < GRAPH_HTML_BUDGET


def test_determinism_at_scale(scale_run, tmp_path):
    _, out, _, corpus = scale_run
    out2 = tmp_path / "out2"
    assert cli.run(str(corpus), str(out2)) == 0
    for fname in ("clusters.csv", "repeated_logic.csv", "join_edges.csv"):
        assert (out / fname).read_bytes() == (out2 / fname).read_bytes()
