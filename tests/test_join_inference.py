"""Partner-informed join resolution: evidence-based, labeled, never silent."""
import sqlglot
import pytest

from conftest import record_for
from sqlinsight import cooccurrence
from sqlinsight.extract import extract_record
from sqlinsight.parse import PRIMARY_DIALECT, ParsedStatement


def record_with_catalog(sql: str, cat: dict):
    expr = sqlglot.parse_one(sql, read=PRIMARY_DIALECT)
    return extract_record(ParsedStatement("t.sql", 0, PRIMARY_DIALECT, expr), catalog=cat)


TWO_TABLE = """
select o.amount
from sales.orders o
join core.customers c on order_id = c.customer_id
"""


def test_two_table_scope_infers_by_elimination():
    rec = record_for(TWO_TABLE)
    assert len(rec.joins) == 1
    j = rec.joins[0]
    assert j.inference == "partner"
    assert j.canonical() == (
        "core.customers", "sales.orders", "customer_id", "order_id",
    )
    inferred = [c for c in rec.columns if c.status == "join_inferred"]
    assert [(c.table, c.name) for c in inferred] == [("sales.orders", "order_id")]


def test_join_inferred_never_merged_into_resolved():
    rec = record_for(TWO_TABLE)
    statuses = {c.status for c in rec.columns}
    assert "join_inferred" in statuses
    assert all(
        c.status != "resolved" for c in rec.columns if c.name == "order_id"
    )


def test_three_table_scope_stays_dropped_without_catalog():
    sql = """
    select o.amount
    from sales.orders o
    join core.customers c on c.customer_id = o.customer_id
    join core.refunds r on order_id = c.customer_id
    """
    rec = record_for(sql)
    canonicals = {j.canonical() for j in rec.joins}
    assert ("core.customers", "sales.orders", "customer_id", "customer_id") in canonicals
    # order_id had two candidates (orders, refunds): no guess, edge dropped.
    assert all("order_id" not in (j.left_col, j.right_col) for j in rec.joins)


def test_catalog_narrows_three_table_scope_to_one_candidate():
    # order_id exists on BOTH the partner (customers) and refunds, so plain
    # catalog resolution sees two candidates and stays ambiguous; partner
    # inference excludes the partner side and lands on refunds.
    sql = """
    select o.amount
    from sales.orders o
    join core.customers c on c.customer_id = o.customer_id
    join core.refunds r on order_id = c.customer_id
    """
    cat = {"core.customers": {"order_id"}, "core.refunds": {"order_id"}}
    rec = record_with_catalog(sql, cat)
    inferred = [j for j in rec.joins if j.inference == "partner"]
    assert len(inferred) == 1
    tables = {inferred[0].left_table, inferred[0].right_table}
    assert tables == {"core.refunds", "core.customers"}


def test_derived_source_in_scope_blocks_inference():
    sql = """
    with recent as (select o.order_id from sales.orders o)
    select c.name
    from core.customers c
    join recent r on order_id = c.customer_id
    """
    rec = record_for(sql)
    assert all(j.inference == "" for j in rec.joins)
    assert all(c.status != "join_inferred" for c in rec.columns)


def test_inferred_only_pairs_reported():
    recs = [record_for(TWO_TABLE)]
    assert cooccurrence.partner_inferred_pairs(recs) == {
        ("core.customers", "sales.orders")
    }
    edges = cooccurrence.join_edges(recs)
    assert edges[0][5] == "partner"


@pytest.mark.parametrize("sql", [
    "select a.x=b.x as same from ta a cross join tb b",
    "select a.x from ta a cross join tb b where a.x=b.x",
    "select a.x from ta a join tb b on exists "
    "(select 1 from tc c cross join td d where c.x=d.x)",
])
def test_non_join_comparisons_do_not_create_edges(sql):
    rec = record_for(sql)
    assert rec.joins == []
    assert all(c.context != "join" and c.status != "join_inferred" for c in rec.columns)
