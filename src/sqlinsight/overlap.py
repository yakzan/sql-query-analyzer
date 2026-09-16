"""Detect repeated logic blocks (CTEs and inline subqueries) across the corpus.

Two signals:
  - exact: identical normalized SQL (copy-paste reuse)
  - near_dupe: token-level similarity (same logic with renames, added
    filters, changed literals)

Similarity is a blend measured on literal-masked tokens:
  0.5 * Jaccard(5-token shingles) + 0.5 * Jaccard(token sets)
The shingle half rewards preserved structure; the token half keeps recall on
small CTEs, where inserting one clause disrupts most 5-grams (a WHERE added
to a 12-token CTE drops shingle Jaccard to ~0.33 while token Jaccard stays
~0.73). Unrelated queries score near zero on both halves.

MinHash/LSH over the token space only prunes candidate pairs (tuned
permissively, ~0.42); the blended exact Jaccard is the arbiter. Everything is
deterministic: fixed-seed permutations, exact confirmation, sorted outputs.
"""
from __future__ import annotations

import hashlib
import random
from collections import defaultdict

from sqlglot import Dialect
from sqlglot.tokens import TokenType

from .models import CteInfo, QueryRecord

SHINGLE_K = 5
MINHASH_PERMS = 128
LSH_BANDS = 32  # 32 bands x 4 rows: candidate threshold ~ (1/32)^(1/4) = 0.42
SIMILARITY_THRESHOLD = 0.45
_PRIME = (1 << 61) - 1

_rnd = random.Random(42)
_PERM_PARAMS = [
    (_rnd.randrange(1, _PRIME), _rnd.randrange(0, _PRIME))
    for _ in range(MINHASH_PERMS)
]


def collect_units(records: list[QueryRecord]) -> list[CteInfo]:
    units: list[CteInfo] = []
    for rec in records:
        units.extend(rec.ctes)
        units.extend(rec.subqueries)
    return units


def collect_ctes(records: list[QueryRecord]) -> list[CteInfo]:
    return [u for u in collect_units(records) if u.unit_type == "cte"]


def _mask_literals(norm_sql: str) -> str:
    try:
        tokens = Dialect.get_or_raise("redshift").tokenize(norm_sql)
    except Exception:  # noqa: BLE001 - never fall back to emitting unredacted SQL
        return "?"
    literal_types = {
        TokenType.STRING, TokenType.NUMBER, TokenType.BIT_STRING,
        TokenType.HEX_STRING, TokenType.BYTE_STRING, TokenType.NATIONAL_STRING,
        TokenType.RAW_STRING, TokenType.HEREDOC_STRING, TokenType.UNICODE_STRING,
    }
    for token in reversed(tokens):
        if token.token_type in literal_types:
            norm_sql = norm_sql[:token.start] + "?" + norm_sql[token.end + 1:]
    return norm_sql


def _hash64(text: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big"
    )


class _Fingerprint:
    """Token set + 5-token shingle set of a unit's literal-masked SQL."""

    def __init__(self, norm_sql: str):
        tokens = _mask_literals(norm_sql).split()
        self.token_set = frozenset(_hash64(t) for t in tokens)
        if len(tokens) <= SHINGLE_K:
            grams = [" ".join(tokens)]
        else:
            grams = [
                " ".join(tokens[i : i + SHINGLE_K])
                for i in range(len(tokens) - SHINGLE_K + 1)
            ]
        self.shingle_set = frozenset(_hash64(g) for g in grams)


def _minhash(values: frozenset[int]) -> tuple[int, ...]:
    return tuple(
        min((a * v + b) % _PRIME for v in values) for a, b in _PERM_PARAMS
    )


def _jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _similarity(a: _Fingerprint, b: _Fingerprint) -> float:
    return 0.5 * _jaccard(a.shingle_set, b.shingle_set) + 0.5 * _jaccard(
        a.token_set, b.token_set
    )


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            # Anchor to the smaller index so grouping is order-independent.
            lo, hi = min(ri, rj), max(ri, rj)
            self.parent[hi] = lo


def _grouped_units(
    records: list[QueryRecord],
) -> list[list[tuple[CteInfo, _Fingerprint]]]:
    units = collect_units(records)
    if not units:
        return []
    uf = _UnionFind(len(units))

    first_by_hash: dict[str, int] = {}
    for i, u in enumerate(units):
        if u.exact_hash in first_by_hash:
            uf.union(first_by_hash[u.exact_hash], i)
        else:
            first_by_hash[u.exact_hash] = i

    prints = [_Fingerprint(u.normalized_sql) for u in units]
    signatures = [_minhash(p.token_set) for p in prints]
    rows_per_band = MINHASH_PERMS // LSH_BANDS
    checked: set[tuple[int, int]] = set()
    for band in range(LSH_BANDS):
        buckets: dict[tuple[int, ...], list[int]] = defaultdict(list)
        lo = band * rows_per_band
        for i, sig in enumerate(signatures):
            buckets[sig[lo : lo + rows_per_band]].append(i)
        for members in buckets.values():
            for ai in range(len(members)):
                for bi in range(ai + 1, len(members)):
                    pair = (members[ai], members[bi])
                    if pair in checked:
                        continue
                    checked.add(pair)
                    if units[pair[0]].exact_hash == units[pair[1]].exact_hash:
                        continue
                    if _similarity(prints[pair[0]], prints[pair[1]]) >= SIMILARITY_THRESHOLD:
                        uf.union(*pair)

    by_root: dict[int, list[int]] = defaultdict(list)
    for i in range(len(units)):
        by_root[uf.find(i)].append(i)

    return [
        [(units[i], prints[i]) for i in idxs]
        for _, idxs in sorted(by_root.items())
        if len(idxs) >= 2
    ]


def _group_similarity(group: list[tuple[CteInfo, _Fingerprint]]) -> float:
    if len({u.exact_hash for u, _ in group}) == 1:
        return 1.0
    sims = [
        _similarity(group[i][1], group[j][1])
        for i in range(len(group))
        for j in range(i + 1, len(group))
    ]
    return min(sims) if sims else 1.0


def _row(group: list[tuple[CteInfo, _Fingerprint]]) -> dict:
    members = [u for u, _ in group]
    distinct_hashes = {u.exact_hash for u in members}
    match_type = "exact" if len(distinct_hashes) == 1 else "near_dupe"
    similarity = _group_similarity(group)
    files = sorted({u.file for u in members})
    names = sorted({u.name for u in members})
    types = sorted({u.unit_type for u in members})
    tables = sorted({t for u in members for t in u.tables})
    sample = _mask_literals(
        min(members, key=lambda u: (u.file, u.stmt_index, u.name)).normalized_sql
    )
    if len(sample) > 600:
        sample = sample[:600] + " ..."
    return {
        "match_type": match_type,
        "key": min(distinct_hashes)[:12],
        "occurrences": len(group),
        "distinct_files": len(files),
        "similarity": f"{similarity:.2f}",
        "unit_types": ", ".join(types),
        "unit_names": ", ".join(names),
        "files": ", ".join(files),
        "tables": ", ".join(tables),
        "sample_sql": sample,
    }


def repeated_logic(records: list[QueryRecord]) -> list[dict]:
    rows = [_row(g) for g in _grouped_units(records)]
    # Consolidation ROI: many occurrences of highly similar logic first.
    rows.sort(
        key=lambda r: (
            -r["occurrences"] * float(r["similarity"]),
            r["match_type"],
            r["key"],
        )
    )
    return rows


def repeated_unit_keys(
    records: list[QueryRecord],
) -> set[tuple[str, int, str, str]]:
    """Identity keys of units confirmed repeated, for cluster evidence."""
    return {
        (u.file, u.stmt_index, u.name, u.exact_hash)
        for group in _grouped_units(records)
        for u, _ in group
    }
