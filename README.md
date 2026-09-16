# sqlinsight

A deterministic analysis tool for large collections of raw SQL. It parses your
queries, extracts a structured inventory (tables, columns, joins, CTEs), and
produces co-occurrence statistics, repeated-logic detection, and cluster
suggestions to help dbt designers find where to start modeling.

It is **decision support, not auto-modeling**. Extraction and co-occurrence are
static observations subject to parser and catalog coverage; clusters are
heuristic starting points that still need human judgment.

## What it produces

For a corpus of `.sql` files it emits (into `output/`):

- `inventory.sqlite` - **the primary artifact**: normalized records plus every
  stat table, ready for ad-hoc SQL (schema below)
- `report.html` - browsable summary with sortable/searchable tables
- `graph.html` - interactive join graph (offline), nodes colored by cluster,
  dashed edges = partner-inferred, capped at the top `--graph-edges` (default
  200) join edges by frequency
- `table_frequency.csv`, `table_cooccurrence.csv`, `column_cooccurrence.csv`
- `join_edges.csv` - table pairs and the keys they join on, with frequency and
  an `inference` flag for partner-inferred edges
- `repeated_logic.csv` - reused CTE/inline-subquery blocks (`exact` = identical SQL, `near_dupe` = token-level similar with literals masked), ranked by occurrences x similarity
- `clusters.csv` - communities of join-coupled tables (suggestions, not models)
- `parse_errors.log`

### inventory.sqlite schema

Normalized inventory tables:

| table | columns |
|---|---|
| `schema_info` | schema version for consumers |
| `queries` | file, stmt_index, parse_ok, dialect, error, kind, target_table, n_tables, n_joins, n_ctes |
| `query_tables` | file, stmt_index, table_name |
| `columns` | file, stmt_index, table_name, column_name, status, context |
| `joins` | file, stmt_index, left_table, right_table, left_col, right_col, inference |
| `logic_units` | name, file, stmt_index, unit_type (`cte`/`subquery`), tables, output_columns, exact_hash, signature |

Plus one table per CSV (`table_frequency`, `table_cooccurrence`,
`column_cooccurrence`, `join_edges`, `repeated_logic`, `clusters`) with the
same columns as the CSV headers. Counts and similarity values use numeric
SQLite types, and common table/column/join/hash lookups are indexed. Example:

```bash
sqlite3 output/inventory.sqlite \
  "select table_name, count(*) from columns where status='ambiguous' group by 1 order by 2 desc"
```

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

# With the real warehouse schema (optional): resolves far more columns and
# expands SELECT *. Format: {"schema.table": ["col", ...]}
uv run sqlinsight path/to/sql_files -o output --catalog schema.json
```

Without `--catalog`, a table->columns map is inferred from qualified
references across the corpus (offline fallback). When provided, the real
catalog wins per table.

Then open `output/report.html`.

## How it works

1. **Parse** - static dbt `ref()` / `source()` relation macros are resolved,
   then `sqlglot` parses Redshift with a Postgres fallback. Unparseable files
   are logged with location-only errors and skipped, never crashing the run.
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

A scale gate (`uv run pytest -m slow`) runs the full pipeline on a seeded
80-file synthetic corpus with planted ground truth (exact dupes, near-dupes,
composite keys, wide queries, inserts) and asserts recall, runtime, artifact
size, cluster shape, and determinism.

## Security and privacy

Analysis is local and generated HTML has no runtime network dependency. Output
paths are portable corpus-relative paths; parser errors omit SQL excerpts; and
the SQL samples in `repeated_logic.csv` / `report.html` replace string and
numeric literals with `?` using dialect-aware SQL tokens, including escaped strings.
The graph embeds its JavaScript/CSS and removes Pyvis's unused Bootstrap CDN
resources.

No warehouse credentials are needed: inputs are local SQL files and an optional
schema JSON file. Keep credentials out of the repository; `.env` and `.env.*`
are ignored (except sanitized `.env.example` files). This does not protect
secrets already tracked by Git or placed in other files.

Artifacts still contain structural metadata—including file, schema, table,
and column names—because that is the product's purpose. Treat the output
directory as sensitive warehouse metadata and review it before sharing. Raw
SQL is not emitted, but identifiers and hashes can still disclose internal
structure.

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

- Join edges represent explicit `JOIN ... ON` column equalities, not projected
  comparisons or implicit joins in `WHERE`.
- Catalog attribution is scope-local; an unqualified column stays ambiguous
  when a derived source could also supply it.
- Exact overlap preserves literal case; changing `'ABC'` to `'abc'` is a
  near-duplicate, not an exact duplicate. Normalization changes regenerate
  overlap hashes, so keys are not stable identifiers across versions.
- `SELECT *` columns stay opaque unless a real schema catalog is provided via `--catalog`.
- Inline subqueries under ~25 tokens are not fingerprinted for overlap (deliberate noise filter).
- Only static dbt `ref()` / `source()` calls are preprocessed. Arbitrary Jinja,
  dynamic SQL, stored procedures, and macros are not evaluated.
- Signal quality is tested on a seeded synthetic corpus, not yet on labeled
  production corpora. Repeated-logic and cluster suggestions require human
  validation; no precision claim is made.
