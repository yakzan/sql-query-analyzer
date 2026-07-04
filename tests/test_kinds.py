"""Statement-kind classification: writes are targets, not read relationships."""
from conftest import record_for


def test_insert_select_extracts_reads_and_target():
    rec = record_for("""
    insert into analytics.daily_totals
    select o.customer_id, sum(o.amount) as total
    from sales.orders o
    join core.customers c on o.customer_id = c.customer_id
    group by o.customer_id
    """)
    assert rec.kind == "insert_select"
    assert rec.target_table == "analytics.daily_totals"
    assert rec.tables == ["core.customers", "sales.orders"]
    assert len(rec.joins) == 1


def test_ctas_extracts_reads_and_target():
    rec = record_for("""
    create table analytics.recent as
    with recent as (select o.order_id from sales.orders o)
    select r.order_id from recent r
    """)
    assert rec.kind == "ctas"
    assert rec.target_table == "analytics.recent"
    assert rec.tables == ["sales.orders"]
    assert [c.name for c in rec.ctes] == ["recent"]


def test_insert_values_is_skipped():
    rec = record_for("insert into t values (1, 2)")
    assert rec.kind == "skipped_ddl"
    assert rec.target_table == "t"
    assert rec.tables == []


def test_plain_ddl_is_skipped():
    rec = record_for("create table t (id int, name varchar(10))")
    assert rec.kind == "skipped_ddl"
    assert rec.tables == []
    assert rec.joins == []


def test_delete_is_skipped():
    rec = record_for("delete from sales.orders where id = 1")
    assert rec.kind == "skipped_ddl"
    assert rec.tables == []


def test_plain_select_kind():
    rec = record_for("select a from sales.orders")
    assert rec.kind == "select"
    assert rec.target_table == ""
