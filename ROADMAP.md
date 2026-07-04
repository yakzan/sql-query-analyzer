# sqlinsight roadmap

Improvement plan derived from the post-hardening review (see
`docs/design-notes.md` for the open questions behind each step). Ordered so
each step de-risks the next. Work through it top to bottom; check tasks off
as sessions complete them. Each step should land as its own commit with tests.

Legend: `[ ]` pending, `[x]` done. Update the **Status** line per step as you go.

---

## Step 1 - Determinism + end-to-end snapshot tests

**Status:** done (2026-07-04)
**Why first:** determinism is the flagship guarantee but nothing proves it;
a snapshot harness makes every later diff reviewable.

- [x] Add `tests/test_e2e.py` running `cli.run("examples", tmpdir)` end to end
- [x] Determinism test: run pipeline twice into two tmpdirs, compare all CSVs byte-for-byte
- [x] Compare `inventory.sqlite` between runs (dump each table ordered, compare dumps)
- [x] Compare `report.html` and `graph.html` between runs (assert byte equality)
- [x] Add golden snapshots for `clusters.csv` and `repeated_logic.csv` under `tests/golden/`
- [x] Assert emitted files exactly match golden snapshots (regenerate via `UPDATE_GOLDENS=1`)
- [x] Document in README how to intentionally refresh goldens

**Acceptance:** `uv run pytest -q` proves two runs are byte-identical and
output changes show up as golden diffs.

---

## Step 2 - Explicit non-SELECT statement handling

**Status:** done (2026-07-04)
**Why:** `INSERT INTO ... SELECT` / CTAS / DDL currently yield thin records
and can quietly distort co-occurrence.

- [x] Add `kind` (and `target_table`) fields to `QueryRecord` in `models.py`
- [x] Classify statement root in `extract_record`: select/union -> analyze as now
- [x] `INSERT` / CTAS: record target table separately, extract the embedded SELECT normally
- [x] Keep the write target out of `tables` (a write is not a co-occurrence relationship)
- [x] Pure DDL/DML without SELECT: mark `kind="skipped_ddl"`, exclude from co-occurrence and graph
- [x] Surface skipped/statement-kind counts in the report so nothing disappears silently
- [x] Tests: one each for `INSERT INTO ... SELECT`, `CREATE TABLE AS`, plain DDL

**Acceptance:** non-SELECT statements are either meaningfully extracted or
visibly skipped; co-occurrence contains only read relationships.

---

## Step 3 - Optional real catalog (`--catalog`)

**Status:** done (2026-07-04); `--catalog-dsn` helper deliberately deferred
(would add a db-driver dependency; the JSON format is trivial to produce)
**Why:** inferred table->columns is a workaround; a real catalog removes most
ambiguity and makes `SELECT *` transparent.

- [x] Accept `--catalog path.json` (`{"schema.table": ["col", ...]}`) in `cli.py`
- [x] Loader + validation in `catalog.py`; provided catalog wins per table, inferred stays as fallback
- [x] `SELECT *` expansion using known columns (new status `star_expanded`)
- [x] Ambiguous-column resolution against real catalog (same exactly-one-candidate rule)
- [x] Report metric: `catalog source: inferred | provided (+ merged)`
- [ ] (Optional, deferred) `--catalog-dsn` helper that dumps `information_schema.columns` to the JSON format
- [x] Tests: provided-catalog resolution, star expansion, precedence over inferred

**Acceptance:** running with a catalog measurably reduces ambiguous columns on
`examples/` and stars are expanded; offline inferred mode unchanged.

---

## Step 4 - Join-topology-driven clustering

**Status:** done (2026-07-04)
**Why:** co-occurrence is a weak signal (one wide dashboard query links
unrelated tables); join topology is the real dbt signal. Composite keys
currently inflate degree as separate edges.

### 4a - Collapse composite join keys

- [x] Group raw `JoinEdge`s per statement by canonical table pair
- [x] Emit one relationship per pair per statement (key columns stay in `join_edges()`)
- [x] Aggregate across corpus: edge weight = number of statements with the relationship
- [x] Keep key-column detail in `join_edges.csv`; remove it from graph weight
- [x] Test: composite `(tenant_id, order_id)` join yields one edge, not two

### 4b - Re-weight community detection

- [x] Build community graph from join relationships only (`weight = join_count`)
- [x] Fold co-occurrence in as weak prior: `weight += alpha * cooc_count`, default `alpha = 0.1`
- [x] Apply co-occurrence prior only for pairs co-occurring in >= 2 distinct files
- [x] Expose `--resolution` (default 1.0) passed to `greedy_modularity_communities`
- [x] Tables with no join edges become explicit "unconnected" singletons (clusters.csv `note` column)
- [x] Update goldens; verify the toy corpus no longer collapses into one giant cluster
      (old: one 8-of-11-table blob; new: 5 + 3 + 2 + 1 unconnected)
- [x] Tests: dashboard-query artifact suppressed; determinism preserved

**Acceptance:** clusters follow join topology; wide queries no longer merge
unrelated tables; output still byte-stable across runs.

---

## Step 5 - Token-level near-duplicate overlap (MinHash), incl. inline subqueries

**Status:** done (2026-07-04), with one measured deviation: pure 5-token
shingle Jaccard at 0.7 missed real small-CTE near-dupes (adding one WHERE to a
12-token CTE drops shingle Jaccard to ~0.33). Similarity is instead a blend,
`0.5 * shingle-Jaccard + 0.5 * token-set-Jaccard`, threshold 0.45; measured:
planted near-dupes score 0.46-0.53, unrelated queries ~0.09. LSH prunes
candidates permissively (~0.42); the exact blended Jaccard decides.
**Why:** overlap is pitched as the highest-ROI output but only fingerprints
named CTEs with a crude (tables, output_columns) signature.

- [x] Candidate units: named CTEs + `exp.Subquery` with >= 1 physical table and >= ~25 tokens
- [x] Normalize: lowercase identifiers, strip comments, literals -> `?` placeholder
- [x] k-shingles over token stream (k = 5) + token sets (blended, see above)
- [x] MinHash signatures (128 perms, fixed seed - determinism preserved)
- [x] LSH bucketing (32 bands x 4 rows, ~0.42) as candidate filter; exact blended Jaccard >= 0.45 decides
- [x] Union-find over kept pairs -> duplicate groups (index-anchored, order-independent)
- [x] Exact-hash fast path stays; label groups `exact` vs `near_dupe` with min pairwise similarity
- [x] `repeated_logic.csv`: add `similarity` and `unit_types` (cte | subquery) columns
- [x] Retire the old structural signature (field kept on CteInfo for the sqlite inventory only)
- [x] Rank groups by `occurrences * similarity` descending
- [x] Tests: planted exact dupe, planted near-dupe, changed-literal near-dupe,
      inline subquery detection, tiny-subquery filter, order independence

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
