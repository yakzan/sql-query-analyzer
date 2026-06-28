from conftest import record_for

JOIN_SQL = """
select c.customer_id, c.name, sum(o.amount) as total
from core.customers c
join sales.orders o on c.customer_id = o.customer_id
where o.status = 'active'
group by c.customer_id, c.name
"""


def test_tables_distinguished_from_aliases():
    rec = record_for(JOIN_SQL)
    assert rec.parse_ok
    assert rec.tables == ["core.customers", "sales.orders"]


def test_join_key_extracted_canonically():
    rec = record_for(JOIN_SQL)
    assert len(rec.joins) == 1
    assert rec.joins[0].canonical() == (
        "core.customers", "sales.orders", "customer_id", "customer_id",
    )


def test_column_contexts_and_resolution():
    rec = record_for(JOIN_SQL)
    by = {(c.table, c.name): c for c in rec.columns}
    assert by[("sales.orders", "status")].context == "filter"
    assert by[("sales.orders", "status")].status == "resolved"
    group_names = sorted(c.name for c in rec.group_columns)
    assert group_names == ["customer_id", "name"]


def test_aggregations_captured():
    rec = record_for(JOIN_SQL)
    assert "sum(o.amount)" in rec.aggregations


def test_cte_is_not_counted_as_physical_table():
    sql = """
    with recent as (select o.order_id, o.amount from sales.orders o)
    select r.order_id from recent r
    """
    rec = record_for(sql)
    assert rec.tables == ["sales.orders"]
    assert [c.name for c in rec.ctes] == ["recent"]


def test_cte_with_same_short_name_keeps_qualified_source_table():
    sql = """
    with orders as (select * from sales.orders)
    select * from orders
    """
    rec = record_for(sql)
    assert rec.ctes[0].tables == ["sales.orders"]
