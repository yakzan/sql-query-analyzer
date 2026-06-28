# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project

`sqlinsight` is a deterministic Python CLI that analyzes a corpus of raw SQL
files and produces co-occurrence statistics, repeated-logic detection, and
clustering suggestions to assist dbt modeling. It is decision support, not
auto-modeling.

## Environment & commands

This project is managed with **uv**. Always use uv; do not call `pip` directly.

```bash
uv sync                                  # install deps (incl. dev)
uv run sqlinsight examples -o output     # run the pipeline
uv run pytest -q                         # run the test suite
uv add <pkg>            # add a runtime dependency
uv add --dev <pkg>      # add a dev dependency
```

Python >= 3.11. The package lives under `src/sqlinsight/` (src layout).

## Architecture (pipeline order)

```
parse.py   -> load .sql, parse with sqlglot (redshift, postgres fallback)
extract.py -> AST -> QueryRecord via scope analysis (tables, columns, joins, ctes)
catalog.py -> bootstrap inferred table->columns map, second-pass column resolution
cooccurrence.py -> table/column co-occurrence + join-edge aggregation
overlap.py -> repeated CTE detection (exact hash + structural signature)
graph.py   -> table graph + greedy_modularity communities + cluster rows
report.py  -> CSVs, inventory.sqlite, report.html (jinja2), graph.html (pyvis)
cli.py     -> orchestration / argparse entry point
models.py  -> shared dataclasses (ColumnRef, JoinEdge, CteInfo, QueryRecord)
```

Data flows one direction; `models.py` is the shared vocabulary.

## Non-negotiable conventions

- **Determinism.** Output must be stable across runs. Sort all collections
  before emitting. Use `greedy_modularity_communities` (deterministic), never
  randomized community detection. Seed anything stochastic.
- **Resilience.** A single malformed query must never crash the run. Parsing and
  extraction catch exceptions and record them; partial results are kept.
- **No guessing.** When a column cannot be confidently attributed to a table,
  mark it `ambiguous`. Do not invent table assignments.
- **Honest framing.** Clusters are suggestions. Keep that wording in any
  user-facing output; do not present clusters as finished dbt models.
- **Offline artifacts.** `graph.html` uses `cdn_resources="in_line"` so it works
  without a network. Keep it that way.

## Testing

- Tests live in `tests/` and use golden assertions on small SQL snippets.
- `tests/conftest.py` exposes `record_for(sql)` / `records_for(*sqls)` helpers.
- Add a test alongside any behavior change to extraction, catalog resolution,
  overlap, or clustering. Run `uv run pytest -q` before finishing.

## Code style

- Minimal comments: explain *why* (non-obvious constraints), not *what*.
- Match the existing dataclass-based style in `models.py`.
- Keep modules single-purpose and the pipeline direction intact.
