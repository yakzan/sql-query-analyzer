"""Provided (real) catalog: loading, precedence, and SELECT * expansion."""
import json

import pytest
import sqlglot

from sqlinsight import catalog, cli
from sqlinsight.extract import extract_record
from sqlinsight.parse import PRIMARY_DIALECT, ParsedStatement


def record_with_catalog(sql: str, cat: dict, star_tables: set | None = None):
    expr = sqlglot.parse_one(sql, read=PRIMARY_DIALECT)
    stmt = ParsedStatement("t.sql", 0, PRIMARY_DIALECT, expr)
    return extract_record(stmt, catalog=cat, star_tables=star_tables)


def test_load_provided_normalizes_case(tmp_path):
    p = tmp_path / "cat.json"
    p.write_text(json.dumps({"Sales.Orders": ["Order_ID", "amount"]}))
    cat = catalog.load_provided(p)
    assert cat == {"sales.orders": {"order_id", "amount"}}


def test_load_provided_rejects_bad_shapes(tmp_path):
    p = tmp_path / "cat.json"
    p.write_text(json.dumps({"t": "not-a-list"}))
    with pytest.raises(ValueError):
        catalog.load_provided(p)
    p.write_text(json.dumps(["not", "an", "object"]))
    with pytest.raises(ValueError):
        catalog.load_provided(p)


def test_merge_provided_wins_per_table():
    inferred = {"t": {"a"}, "u": {"x"}}
    provided = {"t": {"b", "c"}}
    merged = catalog.merge(inferred, provided)
    assert merged["t"] == {"b", "c"}
    assert merged["u"] == {"x"}


def test_provided_catalog_resolves_ambiguous_column():
    cat = {"sales.orders": {"amount", "id"}, "core.refunds": {"order_id", "id"}}
    rec = record_with_catalog(
        "select amount from sales.orders o join core.refunds f on o.id = f.order_id",
        cat,
    )
    by = {(c.table, c.name): c for c in rec.columns}
    assert by[("sales.orders", "amount")].status == "catalog_resolved"


def test_star_expansion_only_for_provided_tables():
    cat = {"sales.orders": {"order_id", "amount"}}
    rec = record_with_catalog(
        "select * from sales.orders", cat, star_tables={"sales.orders"}
    )
    expanded = sorted(
        (c.table, c.name) for c in rec.columns if c.status == "star_expanded"
    )
    assert expanded == [("sales.orders", "amount"), ("sales.orders", "order_id")]

    rec = record_with_catalog("select * from sales.orders", cat, star_tables=None)
    assert all(c.status != "star_expanded" for c in rec.columns)


def test_qualified_star_expands_one_table_only():
    cat = {"sales.orders": {"order_id"}, "core.customers": {"customer_id", "name"}}
    rec = record_with_catalog(
        "select o.*, c.name from sales.orders o"
        " join core.customers c on o.customer_id = c.customer_id",
        cat,
        star_tables={"sales.orders", "core.customers"},
    )
    expanded = [(c.table, c.name) for c in rec.columns if c.status == "star_expanded"]
    assert expanded == [("sales.orders", "order_id")]


def test_cli_runs_with_provided_catalog(tmp_path, monkeypatch):
    from test_e2e import REPO_ROOT

    monkeypatch.chdir(REPO_ROOT)
    catfile = tmp_path / "cat.json"
    catfile.write_text(json.dumps({"analytics.orders": ["order_id", "amount"]}))
    out = tmp_path / "out"
    assert cli.run("examples", str(out), catalog_path=str(catfile)) == 0
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "provided (1 tables) + inferred" in html


def test_cli_rejects_invalid_catalog(tmp_path, capsys):
    catfile = tmp_path / "cat.json"
    catfile.write_text("{ not json")
    assert cli.run("examples", str(tmp_path / "out"), catalog_path=str(catfile)) == 1
    assert "cannot load catalog" in capsys.readouterr().err
