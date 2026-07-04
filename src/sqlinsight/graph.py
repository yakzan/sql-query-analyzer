"""Build the table relationship graph and derive cluster suggestions."""
from __future__ import annotations

from collections import defaultdict

import networkx as nx

from .models import QueryRecord
from .overlap import collect_ctes


COOC_ALPHA = 0.1
MIN_COOC_FILES = 2


def build_graph(
    tables: list[str],
    table_cooc: list[tuple[str, str, int]],
    join_rels: list[tuple[str, str, int]],
    cooc_file_counts: dict[tuple[str, str], int] | None = None,
) -> nx.Graph:
    """Join topology drives edge weight; co-occurrence is only a weak prior.

    Co-occurrence captures relationships that never appear as JOIN ON clauses
    (unioned or filtered-together tables), but one wide query links unrelated
    tables, so the prior is damped by COOC_ALPHA and requires the pair to
    co-occur in >= MIN_COOC_FILES distinct files.
    """
    cooc_file_counts = cooc_file_counts or {}
    g = nx.Graph()
    for t in tables:
        g.add_node(t)
    for a, b, n in join_rels:
        g.add_edge(a, b, weight=float(n), joins=n)
    for a, b, c in table_cooc:
        if cooc_file_counts.get((a, b), 0) < MIN_COOC_FILES:
            continue
        if g.has_edge(a, b):
            g[a][b]["weight"] += COOC_ALPHA * c
        else:
            g.add_edge(a, b, weight=COOC_ALPHA * c, joins=0)
    return g


def detect_communities(g: nx.Graph, resolution: float = 1.0) -> list[list[str]]:
    if g.number_of_nodes() == 0:
        return []
    if g.number_of_edges() == 0:
        return [[n] for n in sorted(g.nodes())]
    communities = nx.community.greedy_modularity_communities(
        g, weight="weight", resolution=resolution
    )
    out = [sorted(c) for c in communities]
    out.sort(key=lambda members: (-len(members), members[0] if members else ""))
    return out


def build_clusters(
    records: list[QueryRecord],
    communities: list[list[str]],
    join_rows: list[tuple[str, str, str, str, int]],
) -> list[dict]:
    ctes = collect_ctes(records)
    by_hash: dict[str, list] = defaultdict(list)
    by_sig: dict[str, list] = defaultdict(list)
    for c in ctes:
        by_hash[c.exact_hash].append(c)
        by_sig[c.signature].append(c)

    repeated_keys: set[tuple[str, int, str, str, str]] = set()
    for group in by_hash.values():
        if len(group) >= 2:
            repeated_keys.update(
                (c.file, c.stmt_index, c.name, c.exact_hash, c.signature) for c in group
            )
    for group in by_sig.values():
        if len(group) >= 2 and len({c.exact_hash for c in group}) >= 2:
            repeated_keys.update(
                (c.file, c.stmt_index, c.name, c.exact_hash, c.signature) for c in group
            )

    joined_tables = {t for lt, rt, _lc, _rc, _n in join_rows for t in (lt, rt)}

    rows: list[dict] = []
    for i, members in enumerate(communities):
        member_set = set(members)
        note = (
            "unconnected (no join edges)"
            if len(members) == 1 and members[0] not in joined_tables
            else ""
        )

        supporting = sorted(
            {
                rec.file
                for rec in records
                if len(set(rec.tables) & member_set) >= 2
            }
        )
        internal_joins = [
            f"{lt}.{lc} = {rt}.{rc} (x{n})"
            for lt, rt, lc, rc, n in join_rows
            if lt in member_set and rt in member_set
        ]
        cluster_ctes = sorted(
            {
                c.name
                for c in ctes
                if c.tables
                and set(c.tables) <= member_set
                and (c.file, c.stmt_index, c.name, c.exact_hash, c.signature)
                in repeated_keys
            }
        )
        rows.append(
            {
                "cluster_id": i,
                "size": len(members),
                "tables": ", ".join(members),
                "internal_join_keys": "; ".join(internal_joins),
                "supporting_files": ", ".join(supporting),
                "repeated_ctes": ", ".join(cluster_ctes),
                "note": note,
            }
        )
    return rows
