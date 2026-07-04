from conftest import records_for

from sqlinsight import overlap

CTE = """
with mo as (
    select o.customer_id, sum(o.amount) as total
    from sales.orders o
    group by o.customer_id
)
select mo.customer_id from mo
"""

CTE_NEAR_DUP = """
with mo as (
    select o.customer_id, sum(o.amount) as total
    from sales.orders o
    where o.status = 'completed'
    group by o.customer_id
)
select mo.customer_id from mo
"""

CTE_UNRELATED = """
with px as (
    select p.product_id, min(p.price) as floor_price
    from core.products p
    join core.categories c on p.category_id = c.category_id
    where c.active = true
    group by p.product_id
)
select px.product_id from px
"""


def test_exact_duplicate_cte_detected():
    rows = overlap.repeated_logic(records_for(CTE, CTE))
    exact = [r for r in rows if r["match_type"] == "exact"]
    assert len(exact) == 1
    assert exact[0]["occurrences"] == 2
    assert exact[0]["distinct_files"] == 2
    assert exact[0]["similarity"] == "1.00"


def test_near_duplicate_detected_and_grouped_with_exacts():
    rows = overlap.repeated_logic(records_for(CTE, CTE, CTE_NEAR_DUP))
    assert len(rows) == 1
    row = rows[0]
    assert row["match_type"] == "near_dupe"
    assert row["occurrences"] == 3
    assert 0.45 <= float(row["similarity"]) < 1.0


def test_changed_literals_still_near_dupe():
    a = CTE_NEAR_DUP
    b = CTE_NEAR_DUP.replace("'completed'", "'shipped'")
    rows = overlap.repeated_logic(records_for(a, b))
    assert len(rows) == 1
    assert rows[0]["match_type"] == "near_dupe"


def test_unrelated_ctes_not_grouped():
    rows = overlap.repeated_logic(records_for(CTE, CTE_UNRELATED))
    assert rows == []


def test_unique_cte_not_flagged():
    rows = overlap.repeated_logic(records_for(CTE))
    assert rows == []


def test_inline_subquery_duplicates_detected():
    query = """
    select t.customer_id, t.total
    from (
        select o.customer_id, o.region_id, sum(o.amount) as total,
               count(*) as order_count, max(o.order_date) as last_order
        from sales.orders o
        where o.status = 'completed' and o.amount > 0
        group by o.customer_id, o.region_id
    ) t
    where t.total > 100
    """
    rows = overlap.repeated_logic(records_for(query, query))
    assert len(rows) == 1
    assert rows[0]["match_type"] == "exact"
    assert rows[0]["unit_types"] == "subquery"


def test_tiny_subquery_ignored():
    query = "select a from (select a from t1) x"
    recs = records_for(query, query)
    assert all(r.subqueries == [] for r in recs)


def test_grouping_is_order_independent():
    fwd = overlap.repeated_logic(records_for(CTE, CTE, CTE_NEAR_DUP))
    # Same corpus, different file order: same group shape and similarity.
    rev = overlap.repeated_logic(records_for(CTE_NEAR_DUP, CTE, CTE))
    strip = lambda rows: [
        (r["match_type"], r["occurrences"], r["similarity"]) for r in rows
    ]
    assert strip(fwd) == strip(rev)
