from conftest import records_for

from sqlinsight import cooccurrence, graph

# Two disjoint join groups -> two communities.
ORDERS = (
    "select c.customer_id, o.amount from core.customers c "
    "join sales.orders o on c.customer_id = o.customer_id"
)
PRODUCTS = (
    "select p.product_id, cat.category_name from core.products p "
    "join core.categories cat on p.category_id = cat.category_id"
)


def test_table_cooccurrence_counts():
    recs = records_for(ORDERS, ORDERS)
    cooc = cooccurrence.table_cooccurrence(recs)
    assert cooc == [("core.customers", "sales.orders", 2)]


def test_join_edges_aggregated():
    recs = records_for(ORDERS, ORDERS)
    edges = cooccurrence.join_edges(recs)
    assert edges == [("core.customers", "sales.orders", "customer_id", "customer_id", 2)]


def test_disjoint_join_groups_form_two_clusters():
    recs = records_for(ORDERS, PRODUCTS)
    tables = sorted({t for r in recs for t in r.tables})
    cooc = cooccurrence.table_cooccurrence(recs)
    joins = cooccurrence.join_edges(recs)
    g = graph.build_graph(tables, cooc, joins)
    communities = graph.detect_communities(g)
    assert len(communities) == 2
    members = sorted(sorted(c) for c in communities)
    assert ["core.categories", "core.products"] in members
    assert ["core.customers", "sales.orders"] in members
