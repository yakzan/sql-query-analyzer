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
    assert edges == [
        ("core.customers", "sales.orders", "customer_id", "customer_id", 2, "")
    ]


def _graph_for(recs):
    tables = sorted({t for r in recs for t in r.tables})
    return graph.build_graph(
        tables,
        cooccurrence.table_cooccurrence(recs),
        cooccurrence.join_relationships(recs),
        cooccurrence.cooccurring_file_counts(recs),
    )


def test_disjoint_join_groups_form_two_clusters():
    recs = records_for(ORDERS, PRODUCTS)
    communities = graph.detect_communities(_graph_for(recs))
    assert len(communities) == 2
    members = sorted(sorted(c) for c in communities)
    assert ["core.categories", "core.products"] in members
    assert ["core.customers", "sales.orders"] in members


def test_cluster_repeated_ctes_omits_unique_ctes():
    sql = """
    with tmp as (
        select o.customer_id from sales.orders o
    )
    select c.customer_id
    from core.customers c
    join tmp t on c.customer_id = t.customer_id
    """
    recs = records_for(sql)
    communities = graph.detect_communities(_graph_for(recs))
    clusters = graph.build_clusters(recs, communities, cooccurrence.join_edges(recs))
    assert all(row["repeated_ctes"] == "" for row in clusters)


def test_composite_join_key_is_one_relationship():
    sql = (
        "select o.amount from sales.orders o join core.refunds r "
        "on o.tenant_id = r.tenant_id and o.order_id = r.order_id"
    )
    recs = records_for(sql)
    assert len(cooccurrence.join_edges(recs)) == 2  # key detail preserved
    rels = cooccurrence.join_relationships(recs)
    assert rels == [("core.refunds", "sales.orders", 1)]  # graph sees one edge
    g = _graph_for(recs)
    assert g["core.refunds"]["sales.orders"]["joins"] == 1


def test_single_file_cooccurrence_adds_no_edge():
    # One wide query without joins: weak evidence, no community edge.
    wide = "select a.x, b.y, c.z from ta a, tb b, tc c"
    recs = records_for(wide)
    g = _graph_for(recs)
    assert g.number_of_edges() == 0
    communities = graph.detect_communities(g)
    assert all(len(c) == 1 for c in communities)


def test_repeated_cooccurrence_across_files_adds_weak_prior_edge():
    unioned = "select x from ta union all select x from tb"
    recs = records_for(unioned, unioned)  # two distinct files
    g = _graph_for(recs)
    assert g.has_edge("ta", "tb")
    assert g["ta"]["tb"]["joins"] == 0
    assert g["ta"]["tb"]["weight"] < 1  # prior stays weaker than one real join


def test_unconnected_singleton_labeled():
    recs = records_for("select x from lonely", ORDERS)
    g = _graph_for(recs)
    communities = graph.detect_communities(g)
    clusters = graph.build_clusters(recs, communities, cooccurrence.join_edges(recs))
    by_tables = {row["tables"]: row for row in clusters}
    assert by_tables["lonely"]["note"] == "unconnected (no join edges)"
    assert by_tables["core.customers, sales.orders"]["note"] == ""
