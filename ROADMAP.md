# sqlinsight roadmap

Improvement plan derived from the post-hardening review (see
`docs/design-notes.md` for the open questions behind each step). Ordered so
each step de-risks the next. Work through it top to bottom; check tasks off
as sessions complete them. Each step should land as its own commit with tests.

Legend: `[ ]` pending, `[x]` done. Update the **Status** line per step as you go.

---

## Step 1 - Determinism + end-to-end snapshot tests

**Status:** not started
**Why first:** determinism is the flagship guarantee but nothing proves it;
a snapshot harness makes every later diff reviewable.

- [ ] Add `tests/test_e2e.py` running `cli.run("examples", tmpdir)` end to end
- [ ] Determinism test: run pipeline twice into two tmpdirs, compare all CSVs byte-for-byte
- [ ] Compare `inventory.sqlite` between runs (dump each table ordered, compare dumps)
- [ ] Compare `report.html` and `graph.html` between runs (assert byte equality)
- [ ] Add golden snapshots for `clusters.csv` and `repeated_logic.csv` under `tests/golden/`
- [ ] Assert emitted files exactly match golden snapshots (regenerate via a documented flag or helper)
- [ ] Document in README how to intentionally refresh goldens

**Acceptance:** `uv run pytest -q` proves two runs are byte-identical and
output changes show up as golden diffs.

---

## Step 2 - Explicit non-SELECT statement handling

**Status:** not started
**Why:** `INSERT INTO ... SELECT` / CTAS / DDL currently yield thin records
and can quietly distort co-occurrence.

- [ ] Add `kind` (and `target_table`) fields to `QueryRecord` in `models.py`
- [ ] Classify statement root in `extract_record`: select/union -> analyze as now
- [ ] `INSERT` / CTAS: record target table separately, extract the embedded SELECT normally
- [ ] Keep the write target out of `tables` (a write is not a co-occurrence relationship)
- [ ] Pure DDL/DML without SELECT: mark `kind="skipped_ddl"`, exclude from co-occurrence and graph
- [ ] Surface skipped/statement-kind counts in the report so nothing disappears silently
- [ ] Tests: one each for `INSERT INTO ... SELECT`, `CREATE TABLE AS`, plain DDL

**Acceptance:** non-SELECT statements are either meaningfully extracted or
visibly skipped; co-occurrence contains only read relationships.

---

## Step 3 - Optional real catalog (`--catalog`)

**Status:** not started
**Why:** inferred table->columns is a workaround; a real catalog removes most
ambiguity and makes `SELECT *` transparent.

- [ ] Accept `--catalog path.json` (`{"schema.table": ["col", ...]}`) in `cli.py`
- [ ] Loader + validation in `catalog.py`; provided catalog wins per table, inferred stays as fallback
- [ ] `SELECT *` expansion using known columns (new status `star_expanded`)
- [ ] Ambiguous-column resolution against real catalog (same exactly-one-candidate rule)
- [ ] Report metric: `catalog source: inferred | provided (+ merged)`
- [ ] (Optional) `--catalog-dsn` helper that dumps `information_schema.columns` to the JSON format
- [ ] Tests: provided-catalog resolution, star expansion, precedence over inferred

**Acceptance:** running with a catalog measurably reduces ambiguous columns on
`examples/` and stars are expanded; offline inferred mode unchanged.

---

## Step 4 - Join-topology-driven clustering

**Status:** not started
**Why:** co-occurrence is a weak signal (one wide dashboard query links
unrelated tables); join topology is the real dbt signal. Composite keys
currently inflate degree as separate edges.

### 4a - Collapse composite join keys

- [ ] Group raw `JoinEdge`s per statement by canonical table pair
- [ ] Emit one relationship per pair per statement with `key_columns: sorted[(lc, rc), ...]`
- [ ] Aggregate across corpus: edge weight = number of statements with the relationship
- [ ] Keep key-column detail in `join_edges.csv`; remove it from graph weight
- [ ] Test: composite `(tenant_id, order_id)` join yields one edge, not two

### 4b - Re-weight community detection

- [ ] Build community graph from join relationships only (`weight = join_count`)
- [ ] Fold co-occurrence in as weak prior: `weight += alpha * cooc_count`, default `alpha = 0.1`
- [ ] Apply co-occurrence prior only for pairs co-occurring in >= 2 distinct files
- [ ] Expose `--resolution` (default 1.0) passed to `greedy_modularity_communities`
- [ ] Tables with no join edges become explicit "unconnected" singletons
- [ ] Update goldens; verify the toy corpus no longer collapses into one giant cluster
- [ ] Tests: dashboard-query artifact suppressed; determinism preserved

**Acceptance:** clusters follow join topology; wide queries no longer merge
unrelated tables; output still byte-stable across runs.

---

## Step 5 - Token-level near-duplicate overlap (MinHash), incl. inline subqueries

**Status:** not started
**Why:** overlap is pitched as the highest-ROI output but only fingerprints
named CTEs with a crude (tables, output_columns) signature.

- [ ] Candidate units: named CTEs + `exp.Subquery` with >= 1 physical table and >= ~25 tokens
- [ ] Normalize AST: lowercase identifiers, strip comments, literals -> `?` placeholder
- [ ] k-shingles over token stream (k = 5)
- [ ] MinHash signatures (128 perms, fixed seed - determinism preserved)
- [ ] LSH bucketing tuned for ~0.7 similarity; exact Jaccard on candidate pairs; keep `>= 0.7`
- [ ] Union-find over kept pairs -> duplicate groups
- [ ] Exact-hash fast path stays; label groups `exact` vs `near_dupe` with min pairwise similarity
- [ ] `repeated_logic.csv`: add `similarity` and `unit_type` (cte | subquery) columns
- [ ] Retire (or demote to hint) the old structural signature
- [ ] Rank groups by `occurrences * similarity` descending
- [ ] Tests: planted exact dupe, planted ~0.8 near-dupe, inline subquery detection, determinism

**Acceptance:** near-dupes with renamed CTEs / inline subqueries are found,
ranked by consolidation ROI, fully deterministic.

---

## Step 6 - Partner-informed join resolution

**Status:** not started
**Why:** joins with one ambiguous side vanish from the graph even when the
resolved partner is strong evidence. Extend "no guessing" carefully.

- [ ] In `_extract_joins`: when one side resolves to T and the other is ambiguous, attempt inference
- [ ] Resolve iff exactly one candidate table via catalog, or exactly one unresolved source remains in scope
- [ ] New distinct status `join_inferred` (never merged into `resolved`)
- [ ] Include inferred edges in graph; flag them in `join_edges.csv` (`inference: partner`)
- [ ] Render inferred edges visually distinct (dashed) in `graph.html`
- [ ] Tests: recoverable case resolved and labeled; genuinely ambiguous case still dropped

**Acceptance:** recovered edges are visible, labeled, and excludable; nothing
is silently guessed.

---

## Step 7 - Synthetic scale corpus + performance gate

**Status:** not started
**Why:** validated on 5 files, targeted at ~100; pyvis size, runtime, and
cluster shape at scale are unverified.

- [ ] Seeded generator `tests/gen_corpus.py` (seed 42): ~80 files over a ~60-table synthetic schema
- [ ] Plant ground truth: X exact duplicate CTEs, Y near-dupes at ~0.8, Z composite-key joins, wide 15-table queries, some `INSERT INTO ... SELECT`
- [ ] Smoke test (marked `slow`): full pipeline on generated corpus
- [ ] Assert runtime < 30s
- [ ] Assert planted-duplicate recall matches ground truth
- [ ] Assert no community holds > 60% of connected tables
- [ ] Assert `graph.html` < 3MB
- [ ] Wire into CI/dev docs (`uv run pytest -m slow`)

**Acceptance:** the pipeline is validated at target scale before anyone trusts
it on a real corpus.

---

## Step 8 - Report layer simplification (lowest priority)

**Status:** not started

- [ ] Declare `inventory.sqlite` the primary artifact; document its schema in README
- [ ] Graph at scale: render only top-K join edges by weight (`--graph-edges`, default 200) with a truncation note
- [ ] Freeze the HTML report feature set (no new features; keep CSVs and summary)

**Acceptance:** artifacts stay useful at 100 files; sqlite is the documented
source of truth.

---

## Process rules (apply to every step)

- [ ] One step = one commit (or a small series), each with its own tests
- [ ] Run `uv run pytest -q` before finishing any session
- [ ] Preserve the non-negotiables: determinism, resilience, no guessing, honest framing, offline artifacts
- [ ] When a step changes user-visible output, update goldens deliberately and review the diff
- [ ] Graduate resolved design questions from `docs/design-notes.md` per its own protocol
