import sqlglot

from conftest import records_for

from sqlinsight import catalog
from sqlinsight.extract import extract_all
from sqlinsight.parse import PRIMARY_DIALECT, ParsedStatement

TEACH = "select o.amount, o.order_id from sales.orders o"
AMBIGUOUS = (
    "select amount from sales.orders o "
    "join core.customers c on o.order_id = c.customer_id"
)


def test_catalog_built_from_qualified_refs():
    recs = records_for(TEACH)
    cat = catalog.build_catalog(recs)
    assert "amount" in cat["sales.orders"]
    assert "order_id" in cat["sales.orders"]


def test_refine_resolves_ambiguous_via_inferred_catalog():
    recs = records_for(TEACH, AMBIGUOUS)
    cat = catalog.build_catalog(recs)

    amb = recs[1]
    before = {(c.name, c.status) for c in amb.columns}
    assert ("amount", "ambiguous") in before

    stats = catalog.refine(recs, cat)
    assert stats["catalog_resolved"] == 1

    resolved = next(c for c in amb.columns if c.name == "amount")
    assert resolved.status == "catalog_resolved"
    assert resolved.table == "sales.orders"


def test_refine_with_statements_rebuilds_join_edges_after_resolution():
    teach = "select o.order_id from sales.orders o"
    join_sql = (
        "select * from sales.orders o "
        "join core.customers c on order_id = c.customer_id"
    )
    statements = [
        ParsedStatement("q0.sql", 0, PRIMARY_DIALECT, sqlglot.parse_one(teach, read=PRIMARY_DIALECT)),
        ParsedStatement("q1.sql", 1, PRIMARY_DIALECT, sqlglot.parse_one(join_sql, read=PRIMARY_DIALECT)),
    ]
    records = extract_all(statements)
    cat = catalog.build_catalog(records)

    stats = catalog.refine(records, cat, statements)
    assert stats["catalog_resolved"] == 1
    assert records[1].joins[0].canonical() == (
        "core.customers", "sales.orders", "customer_id", "order_id",
    )
