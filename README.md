# sqlinsight

A deterministic analysis tool for large collections of raw SQL. It parses your
queries, extracts a structured inventory (tables, columns, joins, CTEs), and
produces co-occurrence statistics, repeated-logic detection, and cluster
suggestions to help dbt designers find where to start modeling.

It is **decision support, not auto-modeling**. The extraction and co-occurrence
layers are exact facts; the clusters are heuristic starting points that still
need human judgment.

## What it produces

For a corpus of `.sql` files it emits (into `output/`):

- `report.html` - browsable summary with sortable/searchable tables
- `graph.html` - interactive join graph (offline), nodes colored by cluster
- `inventory.sqlite` - normalized records (queries, tables, columns, joins, ctes) + all stat tables
- `table_frequency.csv`, `table_cooccurrence.csv`, `column_cooccurrence.csv`
- `join_edges.csv` - table pairs and the keys they join on, with frequency
- `repeated_logic.csv` - reused CTE/subquery blocks (`exact` = identical SQL, `structural` = same tables/outputs, differing SQL)
- `clusters.csv` - communities of tightly-coupled tables
- `parse_errors.log`

## Requirements

- [uv](https://docs.astral.sh/uv/) and Python >= 3.11
- SQL dialect: Redshift (falls back to Postgres per statement on parse error)

## Setup

```bash
uv sync
```

## Usage

```bash
# Analyze a directory of .sql files (recurses)
uv run sqlinsight path/to/sql_files -o output

# Run against the bundled examples
uv run sqlinsight examples -o output

# Scope to one set
uv run sqlinsight examples/hard -o output
```

Then open `output/report.html`.

## How it works

1. **Parse** - `sqlglot` (Redshift, Postgres fallback); unparseable files are logged and skipped, never crashing the run.
2. **Extract** - scope analysis attributes columns to their physical source table and distinguishes real tables from CTE/subquery aliases.
3. **Infer catalog** - because no schema catalog is assumed, a `table -> columns` map is bootstrapped from qualified references across the corpus, then a second pass resolves some otherwise-ambiguous columns. Genuinely ambiguous columns are flagged, not guessed.
4. **Co-occurrence + overlap** - table/column co-occurrence and repeated-logic detection.
5. **Graph + clusters** - a table relationship graph with deterministic community detection (`greedy_modularity_communities`).

## Examples

- `examples/simple/` - small single/two-table joins.
- `examples/hard/` - long queries with nested CTEs, a deliberately duplicated block (exact overlap) and a near-duplicate (structural overlap), plus unqualified columns and a `SELECT *`.

## Tests

```bash
uv run pytest -q
```

End-to-end tests prove determinism (two runs must be byte-identical) and
compare `clusters.csv` / `repeated_logic.csv` against golden snapshots in
`tests/golden/`. When an intended behavior change shifts those outputs,
refresh the goldens deliberately and review the diff:

```bash
UPDATE_GOLDENS=1 uv run pytest -q
```

## Architecture & roadmap

- `docs/architecture.html` - self-contained interactive explainer of the
  pipeline: click each stage for its algorithm and a worked example traced
  through the whole flow. Works offline; just open it in a browser.
- `ROADMAP.md` - the agreed improvement plan as checkable steps (snapshot
  tests, join-topology clustering, MinHash overlap, real-catalog support,
  scale validation). One step per commit; check tasks off as they land.
- `docs/design-notes.md` - the open design questions behind the roadmap and
  the tradeoffs that were weighed.

## Known limitations

Each limitation maps to a planned fix in `ROADMAP.md`:

- Only named CTEs are fingerprinted for overlap; inline subqueries are not yet (step 5).
- Near-duplicate detection is signature-based (tables + output columns), not token-level (step 5).
- Composite join keys appear as separate edges, inflating graph degree (step 4a).
- Clustering is driven mostly by co-occurrence, a weaker signal than join topology;
  one wide query can pull unrelated tables into a cluster (step 4b).
- `SELECT *` columns stay opaque without a real schema catalog (step 3).
- Non-SELECT statements (`INSERT INTO ... SELECT`, CTAS, DDL) yield thin records
  rather than being properly extracted or explicitly skipped (step 2).
- Validated on a small example corpus; behavior at the ~100-file target scale
  is not yet exercised by tests (steps 1, 7).
