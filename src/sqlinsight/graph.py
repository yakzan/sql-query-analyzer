"""Build the table relationship graph and derive cluster suggestions."""
from __future__ import annotations

from collections import defaultdict

import networkx as nx

from .models import QueryRecord
from .overlap import collect_ctes


def build_graph(
    tables: list[str],
    table_cooc: list[tuple[str, str, int]],
    join_rows: list[tuple[str, str, str, str, int]],
) -> nx.Graph:
    g = nx.Graph()
    for t in tables:
        g.add_node(t)
    for a, b, c in table_cooc:
        g.add_edge(a, b, weight=c, joins=0)
    for lt, rt, _lc, _rc, n in join_rows:
        if g.has_edge(lt, rt):
            g[lt][rt]["joins"] += n
        else:
            g.add_edge(lt, rt, weight=n, joins=n)
    return g


def detect_communities(g: nx.Graph) -> list[list[str]]:
    if g.number_of_nodes() == 0:
        return []
    if g.number_of_edges() == 0:
        return [[n] for n in sorted(g.nodes())]
    communities = nx.community.greedy_modularity_communities(g, weight="weight")
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

    rows: list[dict] = []
    for i, members in enumerate(communities):
        member_set = set(members)

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
            }
        )
    return rows
