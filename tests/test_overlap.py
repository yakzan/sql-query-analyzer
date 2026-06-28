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


def test_exact_duplicate_cte_detected():
    rows = overlap.repeated_logic(records_for(CTE, CTE))
    exact = [r for r in rows if r["match_type"] == "exact"]
    assert len(exact) == 1
    assert exact[0]["occurrences"] == 2
    assert exact[0]["distinct_files"] == 2


def test_structural_near_duplicate_detected():
    rows = overlap.repeated_logic(records_for(CTE, CTE, CTE_NEAR_DUP))
    structural = [r for r in rows if r["match_type"] == "structural"]
    assert len(structural) == 1
    assert structural[0]["occurrences"] == 3


def test_unique_cte_not_flagged():
    rows = overlap.repeated_logic(records_for(CTE))
    assert rows == []
