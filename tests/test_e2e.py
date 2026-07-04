"""End-to-end pipeline tests: determinism across runs + golden snapshots.

Refresh goldens intentionally with:  UPDATE_GOLDENS=1 uv run pytest -q
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from sqlinsight import cli

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

CSV_FILES = [
    "table_frequency.csv",
    "table_cooccurrence.csv",
    "column_cooccurrence.csv",
    "join_edges.csv",
    "repeated_logic.csv",
    "clusters.csv",
]
GOLDEN_FILES = ["clusters.csv", "repeated_logic.csv"]
ALL_FILES = CSV_FILES + [
    "report.html", "graph.html", "inventory.sqlite", "parse_errors.log",
]


@pytest.fixture()
def run_pipeline(tmp_path, monkeypatch):
    # Relative source keeps file paths in outputs machine-independent.
    monkeypatch.chdir(REPO_ROOT)

    def _run(name: str) -> Path:
        out = tmp_path / name
        assert cli.run("examples", str(out)) == 0
        return out

    return _run


def _sqlite_dump(path: Path) -> str:
    con = sqlite3.connect(path)
    try:
        return "\n".join(con.iterdump())
    finally:
        con.close()


def test_all_artifacts_emitted(run_pipeline):
    out = run_pipeline("out")
    for fname in ALL_FILES:
        assert (out / fname).is_file(), f"missing artifact: {fname}"


def test_two_runs_are_byte_identical(run_pipeline):
    a = run_pipeline("a")
    b = run_pipeline("b")
    for fname in ALL_FILES:
        if fname == "inventory.sqlite":
            assert _sqlite_dump(a / fname) == _sqlite_dump(b / fname), (
                "inventory.sqlite dump differs between runs"
            )
        else:
            assert (a / fname).read_bytes() == (b / fname).read_bytes(), (
                f"{fname} differs between runs"
            )


def test_outputs_match_golden_snapshots(run_pipeline):
    out = run_pipeline("out")
    GOLDEN_DIR.mkdir(exist_ok=True)
    for fname in GOLDEN_FILES:
        golden = GOLDEN_DIR / fname
        if os.environ.get("UPDATE_GOLDENS"):
            shutil.copyfile(out / fname, golden)
            continue
        assert golden.is_file(), (
            f"missing golden {fname}; generate with UPDATE_GOLDENS=1 uv run pytest -q"
        )
        assert (out / fname).read_text(encoding="utf-8") == golden.read_text(
            encoding="utf-8"
        ), f"{fname} deviates from golden; if intended, refresh with UPDATE_GOLDENS=1"
