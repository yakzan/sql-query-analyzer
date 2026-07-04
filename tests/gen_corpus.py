"""Deterministic synthetic corpus generator (seed 42) for scale testing.

Generates ~80 SQL files over a ~60-table schema with planted, known-truth
phenomena: an exact-duplicate CTE group, a near-duplicate CTE group (literal
variants), composite-key joins, wide no-join queries, and INSERT INTO ...
SELECT statements. Returns the ground truth so tests can assert recall.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

SEED = 42
N_TABLES = 60
SCHEMAS = ["core", "sales", "marketing", "finance", "web", "ops"]
BASES = [
    "orders", "customers", "events", "payments", "clicks", "sessions",
    "products", "invoices", "shipments", "refunds", "campaigns", "accounts",
]

EXACT_FILES = 6
NEAR_LITERALS = ["completed", "shipped", "pending", "returned", "failed"]
COMPOSITE_STATEMENTS = 8
INSERT_FILES = 5


@dataclass
class Table:
    name: str
    base: str
    pk: str
    fk_col: str | None = None
    fk_target: "Table | None" = None


@dataclass
class GroundTruth:
    n_files: int
    exact_occurrences: int
    near_occurrences: int
    composite_pair: tuple[str, str]
    composite_keys: tuple[str, str]
    composite_statements: int
    insert_files: int


def _build_tables(rnd: random.Random) -> list[Table]:
    tables: list[Table] = []
    for i in range(N_TABLES):
        base = f"{BASES[i % len(BASES)]}_{i:02d}"
        t = Table(f"{SCHEMAS[i % len(SCHEMAS)]}.{base}", base, f"{base}_id")
        if tables:
            target = tables[rnd.randrange(len(tables))]
            t.fk_col = target.pk
            t.fk_target = target
        tables.append(t)
    return tables


def _join_query(t: Table) -> str:
    tgt = t.fk_target
    if tgt is None:
        return f"select a.{t.pk}, count(*) as n from {t.name} a group by a.{t.pk};"
    return (
        f"select a.{t.pk}, b.{tgt.pk}, sum(a.{t.base}_amount) as total\n"
        f"from {t.name} a\n"
        f"join {tgt.name} b on a.{tgt.pk} = b.{tgt.pk}\n"
        f"where a.{t.base}_status = 'active'\n"
        f"group by a.{t.pk}, b.{tgt.pk};"
    )


def _shared_cte(t: Table, status: str) -> str:
    return (
        f"with shared_metrics as (\n"
        f"    select s.{t.pk}, s.{t.base}_region,\n"
        f"           sum(s.{t.base}_amount) as total_amount,\n"
        f"           count(*) as row_count\n"
        f"    from {t.name} s\n"
        f"    where s.{t.base}_status = '{status}'\n"
        f"    group by s.{t.pk}, s.{t.base}_region\n"
        f")\n"
        f"select shared_metrics.{t.pk}, shared_metrics.total_amount\n"
        f"from shared_metrics;"
    )


def _composite_join(a: Table, b: Table) -> str:
    return (
        f"select x.{a.pk}, sum(x.{a.base}_amount) as total\n"
        f"from {a.name} x\n"
        f"join {b.name} y on x.tenant_id = y.tenant_id and x.{b.pk} = y.{b.pk}\n"
        f"group by x.{a.pk};"
    )


def _wide_query(tables: list[Table]) -> str:
    aliases = [f"t{i}" for i in range(len(tables))]
    cols = ", ".join(f"{a}.{t.pk}" for a, t in zip(aliases, tables))
    frm = ", ".join(f"{t.name} {a}" for a, t in zip(aliases, tables))
    return f"select {cols} from {frm};"


def _insert_select(t: Table) -> str:
    tgt = t.fk_target
    inner = (
        f"select a.{t.pk}, sum(a.{t.base}_amount) as total\n"
        f"from {t.name} a\n"
        f"join {tgt.name} b on a.{tgt.pk} = b.{tgt.pk}\n"
        f"group by a.{t.pk}"
    )
    return f"insert into analytics.rollup_{t.base}\n{inner};"


def generate_corpus(root: Path) -> GroundTruth:
    rnd = random.Random(SEED)
    tables = _build_tables(rnd)
    root.mkdir(parents=True, exist_ok=True)

    exact_table = tables[1]
    near_table = tables[7]
    comp_a, comp_b = tables[2], tables[8]
    joinable = [t for t in tables if t.fk_target is not None]

    files: list[str] = []
    for _ in range(50):
        stmts = [
            _join_query(joinable[rnd.randrange(len(joinable))])
            for _ in range(rnd.randint(1, 2))
        ]
        files.append("\n\n".join(stmts))

    for _ in range(EXACT_FILES):
        files.append(_shared_cte(exact_table, "completed"))

    for literal in NEAR_LITERALS:
        files.append(_shared_cte(near_table, literal))

    files.append(_wide_query(tables[20:35]))
    files.append(_wide_query(tables[36:51]))

    for i in range(INSERT_FILES):
        files.append(_insert_select(joinable[(i * 7) % len(joinable)]))

    comp = [_composite_join(comp_a, comp_b) for _ in range(COMPOSITE_STATEMENTS)]
    # Two composite statements per file across four files, then singles.
    files.append("\n\n".join(comp[0:2]))
    files.append("\n\n".join(comp[2:4]))
    files.extend(comp[4:])

    while len(files) < 80:
        files.append(_join_query(joinable[rnd.randrange(len(joinable))]))

    for i, content in enumerate(files):
        (root / f"q{i:03d}.sql").write_text(content + "\n", encoding="utf-8")

    return GroundTruth(
        n_files=len(files),
        exact_occurrences=EXACT_FILES,
        near_occurrences=len(NEAR_LITERALS),
        composite_pair=tuple(sorted((comp_a.name, comp_b.name))),
        composite_keys=("tenant_id", comp_b.pk),
        composite_statements=COMPOSITE_STATEMENTS,
        insert_files=INSERT_FILES,
    )
