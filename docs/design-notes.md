# Design notes

A place to deliberate, not a backlog. Entries here are open questions about
direction and tradeoffs, not commitments or tasks. They exist to be sat with
until a decision is obvious - and then they graduate (see the bottom of this
file).

The current strategy is sound: determinism (verified byte-identical across
runs), resilience at every pipeline layer, no-guessing on column attribution,
honest "suggestions not models" framing, and offline artifacts. The questions
below are about coverage, scale, and how faithful the two flagship outputs
(overlap and clusters) are to the dbt-modeling decisions they're meant to
support. None of them is a defect in the present behavior; each is a choice
about how far to push.

## Open questions

Captured 2026-06-28, after the hardening commit (`00e2ff1`).

**Update 2026-07-04:** questions 1-8 below have graduated into decisions,
recorded as steps in `ROADMAP.md` (root). The deliberation text is kept here
per the protocol at the bottom of this file, with a one-line `Decision:`
pointer added to each. Two strategic insights that emerged during that review
were not raised here originally and went straight to the roadmap: an optional
*real* catalog (`--catalog`, roadmap step 3) that treats schema inference as a
fallback rather than the design, and report-layer simplification with
`inventory.sqlite` as the primary artifact (roadmap step 8).

### 1. Test coverage breadth vs. snapshot cost

The suite is golden unit tests on tiny snippets via `record_for` (19 tests,
~0.10s). Nothing runs `cli.run` end-to-end on `examples/` and asserts the
CSVs, SQLite schema, or HTML; and despite determinism being the flagship
guarantee, no test *proves* it (verified manually by diffing two runs).
`report.py`'s SQL-string construction and the pyvis output are entirely
untested. The tradeoff: an integration/snapshot test is cheap to add and
de-risks every later change, but snapshots need maintenance when intended
output shifts. How much end-to-end coverage do we want before scaling the
corpus or touching overlap/clustering?

**Decision:** roadmap step 1 - snapshot + determinism tests land first, before
any signal-quality change.

### 2. Scale: validated on 5 files, targeted at ~100

The tool is calibrated and tested against a 5-file toy, but the stated target
is ~100 large files. `graph.html` is already ~700KB at 5 files; at 100 files
with many joins pyvis can produce a multi-MB, laggy page, and `greedy_modularity`
on a dense co-occurrence graph tends to collapse into one giant community plus
singletons (already visible on the toy: cluster 0 holds 8 of 11 tables). Should
we build a larger synthetic smoke corpus (50-100 generated files) to validate
performance and cluster shape before trusting outputs on real corpora?

**Decision:** yes - roadmap step 7, a seeded generator with planted ground
truth and a performance gate.

### 3. What should community detection weight?

`detect_communities` uses `weight="weight"`, which is predominantly table
co-occurrence. But co-occurrence is a weak signal: two tables in one giant
15-table dashboard query co-occur yet may be unrelated, and that single query
pulls them into one community. Join topology is the real dbt signal. The
tradeoff: a join-weighted or join-only community graph (or a resolution
parameter tweak) would likely segment more meaningfully, but co-occurrence
captures relationships that never appear as explicit JOIN ON clauses (e.g.
unioned or filtered-together tables). Determinism is preserved with several
alternatives (seeded Louvain, label propagation). Which signal - or mix -
should drive clusters?

**Decision:** roadmap step 4b - join topology drives weights; co-occurrence
becomes a weak prior (alpha = 0.1, >= 2 distinct files), keeping
greedy_modularity with a --resolution flag.

### 4. Composite join keys as separate edges

A composite FK like `(tenant_id, order_id)` becomes two independent edges,
inflating degree and distorting both the graph and the clusters. For dbt
modeling the join *relationship* is the unit, not the column. Collapsing
multi-column joins into one weighted edge keyed on the table pair would give
cleaner clusters and a cleaner graph, at the cost of hiding which columns form
the key (information that belongs somewhere, just not in the graph weight). Is
collapsing the right default, and if so where does the key detail live?

**Decision:** roadmap step 4a - collapse to one relationship per table pair;
key columns live as metadata in join_edges.csv, out of the graph weight.

### 5. How far should overlap reach?

Overlap is pitched as the highest-ROI output yet is the most limited: only
named CTEs are fingerprinted, and inline subqueries (common in raw analyst SQL)
are skipped, so the signal may be sparse on real corpora. The structural
signature is `(tables, output_columns)` only - it ignores joins and the WHERE
shape, so two queries sharing tables and column names but differing wildly in
logic can register as near-dupes. The tradeoff: extending to inline subqueries
(and maybe whole-query similarity) raises value but also noise; a richer
signature (add join edges + a WHERE-predicate-shape hash) cuts false positives
but narrows what counts as a "near-duplicate." Where is the right line between
recall and precision for a *starting-point* tool?

**Decision:** roadmap step 5 - token-level MinHash/LSH (fixed seed, Jaccard
>= 0.7) over CTEs *and* inline subqueries, ranked by occurrences x similarity;
the coarse structural signature is retired or demoted to a hint.

### 6. Are dropped ambiguous-join edges acceptable?

`_extract_joins` requires both sides resolved, so a genuinely-ambiguous join
column vanishes from `join_edges` and the graph - even when the *other* side of
the equality is strong evidence (e.g. `on order_id = c.customer_id` where
`customers` is known, so `order_id` is very likely the orders table's key). The
catalog-aware rebuild recovers resolvable cases; the 4 "still ambiguous"
columns on the toy show the residual loss. The tradeoff: a join-partner-informed
resolver could recover edges without obviously "guessing" - the partner column
is evidence, not a hunch - but it edges toward the no-guessing line the project
draws deliberately. Is partner-informed resolution consistent with that
principle, or does it break the contract?

**Decision:** roadmap step 6 - consistent, with guardrails: resolve only on
exactly-one-candidate evidence, label with a distinct `join_inferred` status,
render flagged/dashed, and keep it excludable. Nothing silent.

### 7. Non-SELECT statements

Raw corpora include `INSERT INTO ... SELECT`, `CREATE TABLE AS`, and DDL.
`parse_one` accepts them but `extract` is SELECT-centric (`output_columns`
only handles `exp.Select`), so they yield thin or empty records and may pollute
co-occurrence with table lists that aren't query relationships. Should non-SELECT
be extracted (target table + the embedded SELECT), or explicitly skipped and
logged, so they don't quietly distort the graph?

**Decision:** roadmap step 2 - both: INSERT/CTAS get target-table + embedded
SELECT extraction (write target kept out of co-occurrence); pure DDL is
explicitly skipped and surfaced in the report.

### 8. Commit and review cadence

The project landed as one 2024-LOC commit, then a single "gaps found in review"
hardening commit - each fix paired with a regression test. The pattern suggests
issues were caught late, in review, rather than prevented by stage-sliced
commits with per-stage tests. Going forward, does it pay to land pipeline
changes in reviewable slices (parse, extract, catalog, cooccurrence/overlap,
graph, report) with tests at each step, so review finds less and bisect stays
meaningful?

**Decision:** yes - codified as the process rules in ROADMAP.md and the
"Roadmap workflow" section of AGENTS.md: one step per commit, tests per step,
output-changing steps only after the step-1 snapshot harness exists.

## Smaller questions

**Review corrections (2026-09-16):** catalog candidates are now retained per
column scope, including in-place refinement; derived sources block confident
attribution. Join evidence is restricted to explicit `JOIN ... ON` equalities
(implicit WHERE joins remain outside coverage). Exact SQL normalization retains
literal case, while sample redaction uses dialect-aware literal tokens. Generated graphs
remove unused Bootstrap CDN tags rather than relying on Pyvis's `in_line` option
alone. These correct existing contracts rather than add roadmap features.

These three remain genuinely open (deliberately left out of `ROADMAP.md`;
revisit after step 7's scale corpus provides real numbers).

- **Rebuild cost in `refine`.** The catalog-aware path re-traverses scopes and
  re-hashes every CTE per record (~2x extraction). Worth a targeted in-place
  update plus a join re-extraction, or is the rebuild's simplicity worth the
  cost even at 100 files?
- **Parse-error locus (resolved).** `parse_errors.log` now carries line/column
  while deliberately omitting source excerpts and literals from exception
  messages, preserving useful triage without leaking SQL into artifacts.
- **Caching.** Re-runs re-parse everything. For an iterative tool (add a file,
  re-run), is mtime+content-hash AST caching worth it, or premature at this
  corpus size?

## Graduating an entry

When an open question becomes a decision, move it to `docs/adr/` (or open an
issue) and leave a one-line pointer here so this file stays a record of what
was considered, not a graveyard of stale tasks.
