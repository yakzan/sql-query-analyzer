"""Walk parsed SQL ASTs and extract a structured per-query inventory."""
from __future__ import annotations

import hashlib
import json

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from .models import ColumnRef, CteInfo, JoinEdge, QueryRecord
from .parse import ParsedStatement


def _table_name(table: exp.Table) -> str:
    return exp.table_name(table).lower()


def _star_targets(
    select: exp.Expression, table_sources: dict[str, str]
) -> list[str]:
    """Physical tables whose star projections appear in this scope's SELECT."""
    if not isinstance(select, exp.Select):
        return []
    targets: list[str] = []
    for proj in select.expressions:
        if isinstance(proj, exp.Star):
            targets.extend(table_sources.values())
        elif isinstance(proj, exp.Column) and isinstance(proj.this, exp.Star):
            if proj.table in table_sources:
                targets.append(table_sources[proj.table])
    return targets


def _resolve_columns(
    expression: exp.Expression,
    catalog: dict[str, set[str]] | None = None,
    star_tables: set[str] | None = None,
) -> tuple[dict[int, ColumnRef], set[str], list[ColumnRef]]:
    """Map each column node id to a resolved ColumnRef using scope analysis.

    Stars are only expanded for star_tables (backed by a provided catalog);
    the inferred catalog is incomplete by construction, so expanding from it
    would overclaim.
    """
    resolution: dict[int, ColumnRef] = {}
    real_tables: set[str] = set()
    star_refs: list[ColumnRef] = []

    try:
        scopes = traverse_scope(expression)
    except Exception:  # noqa: BLE001 - scope builder can choke on exotic SQL
        scopes = []

    for scope in scopes:
        table_sources: dict[str, str] = {}
        derived_sources: set[str] = set()
        for alias, source in scope.sources.items():
            if isinstance(source, exp.Table):
                tname = _table_name(source)
                table_sources[alias] = tname
                real_tables.add(tname)
            else:
                derived_sources.add(alias)

        lone_table = (
            next(iter(table_sources.values()))
            if len(table_sources) == 1 and not derived_sources
            else None
        )

        for col in scope.columns:
            qualifier = col.table
            if qualifier:
                if qualifier in table_sources:
                    resolution[id(col)] = ColumnRef(
                        table_sources[qualifier], col.name, "resolved", "select"
                    )
                else:
                    resolution[id(col)] = ColumnRef(None, col.name, "derived", "select")
            elif lone_table is not None:
                resolution[id(col)] = ColumnRef(
                    lone_table, col.name, "unqualified_resolved", "select"
                )
            else:
                resolution[id(col)] = ColumnRef(None, col.name, "ambiguous", "select")

        if catalog and star_tables:
            for t in _star_targets(scope.expression, table_sources):
                if t in star_tables and t in catalog:
                    star_refs.extend(
                        ColumnRef(t, name, "star_expanded", "select")
                        for name in sorted(catalog[t])
                    )

    return resolution, real_tables, star_refs


def _extract_joins(
    expression: exp.Expression, resolution: dict[int, ColumnRef]
) -> tuple[list[JoinEdge], set[int]]:
    joins: list[JoinEdge] = []
    join_col_ids: set[int] = set()
    for eq in expression.find_all(exp.EQ):
        left, right = eq.this, eq.expression
        if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
            continue
        lref = resolution.get(id(left))
        rref = resolution.get(id(right))
        if not (lref and rref and lref.table and rref.table):
            continue
        if lref.table == rref.table:
            continue
        join_col_ids.add(id(left))
        join_col_ids.add(id(right))
        joins.append(JoinEdge(lref.table, rref.table, lref.name, rref.name))
    return joins, join_col_ids


def _apply_catalog_resolution(
    resolution: dict[int, ColumnRef],
    real_tables: set[str],
    catalog: dict[str, set[str]],
) -> None:
    for ref in resolution.values():
        if ref.status != "ambiguous":
            continue
        candidates = [
            t for t in sorted(real_tables) if ref.name.lower() in catalog.get(t, set())
        ]
        if len(candidates) == 1:
            ref.table = candidates[0]
            ref.status = "catalog_resolved"


def _assign_context(
    expression: exp.Expression,
    resolution: dict[int, ColumnRef],
    join_col_ids: set[int],
) -> None:
    for col in expression.find_all(exp.Column):
        ref = resolution.get(id(col))
        if ref is None:
            continue
        if id(col) in join_col_ids:
            ref.context = "join"
        elif col.find_ancestor(exp.AggFunc) is not None:
            ref.context = "aggregate"
        elif col.find_ancestor(exp.Group) is not None:
            ref.context = "group"
        elif col.find_ancestor(exp.Where) is not None:
            ref.context = "filter"
        else:
            ref.context = "select"


def _output_columns(select: exp.Expression) -> list[str]:
    if not isinstance(select, exp.Select):
        return []
    out: list[str] = []
    for proj in select.expressions:
        name = proj.alias_or_name
        if name:
            out.append(name.lower())
    return out


def _cte_tables(cte: exp.CTE, cte_names: set[str]) -> list[str]:
    tables: set[str] = set()
    for t in cte.this.find_all(exp.Table):
        name = _table_name(t)
        short = name.split(".")[-1]
        is_qualified = t.args.get("db") is not None or t.args.get("catalog") is not None
        if not is_qualified and short in cte_names:
            continue
        tables.add(name)
    return sorted(tables)


def _normalize_sql(node: exp.Expression) -> str:
    try:
        return node.sql(dialect="redshift", normalize=True, comments=False).lower().strip()
    except Exception:  # noqa: BLE001
        return node.sql().lower().strip()


def _extract_ctes(
    expression: exp.Expression, file: str, stmt_index: int
) -> list[CteInfo]:
    cte_nodes = list(expression.find_all(exp.CTE))
    cte_names = {c.alias.lower() for c in cte_nodes}
    infos: list[CteInfo] = []
    for cte in cte_nodes:
        tables = _cte_tables(cte, cte_names)
        out_cols = _output_columns(cte.this)
        norm = _normalize_sql(cte.this)
        exact_hash = hashlib.sha1(norm.encode("utf-8")).hexdigest()
        signature = json.dumps(
            {"tables": tables, "out": sorted(out_cols)}, sort_keys=True
        )
        infos.append(
            CteInfo(
                name=cte.alias.lower(),
                file=file,
                stmt_index=stmt_index,
                tables=tables,
                output_columns=out_cols,
                normalized_sql=norm,
                exact_hash=exact_hash,
                signature=signature,
            )
        )
    return infos


def _classify(root: exp.Expression) -> tuple[str, str, exp.Expression | None]:
    """Classify a statement: (kind, target_table, expression to analyze).

    Write targets are recorded separately and kept out of read co-occurrence;
    statements with no embedded query are explicitly skipped, not half-read.
    Insert/Create are analyzed at the root: traverse_scope resolves their CTEs
    correctly and never lists the write target as a source.
    """
    if isinstance(root, (exp.Select, exp.SetOperation)):
        return "select", "", root

    if isinstance(root, (exp.Insert, exp.Create)):
        target_node = root.this
        target = ""
        if target_node is not None:
            t = target_node if isinstance(target_node, exp.Table) else target_node.find(exp.Table)
            if t is not None:
                target = _table_name(t)
        if isinstance(root.expression, (exp.Select, exp.SetOperation)):
            kind = "insert_select" if isinstance(root, exp.Insert) else "ctas"
            return kind, target, root
        return "skipped_ddl", target, None

    return "skipped_ddl", "", None


def extract_record(
    stmt: ParsedStatement,
    catalog: dict[str, set[str]] | None = None,
    star_tables: set[str] | None = None,
) -> QueryRecord:
    if stmt.expression is None:
        return QueryRecord(stmt.file, stmt.stmt_index, False, stmt.dialect, stmt.error)

    record = QueryRecord(stmt.file, stmt.stmt_index, True, stmt.dialect)
    record.kind, record.target_table, analyzed = _classify(stmt.expression)
    if analyzed is None:
        return record

    try:
        resolution, real_tables, star_refs = _resolve_columns(
            analyzed, catalog=catalog, star_tables=star_tables
        )
        if catalog is not None:
            _apply_catalog_resolution(resolution, real_tables, catalog)
        joins, join_col_ids = _extract_joins(analyzed, resolution)
        _assign_context(analyzed, resolution, join_col_ids)

        record.tables = sorted(real_tables)
        record.columns = list(resolution.values()) + star_refs
        record.joins = joins
        record.group_columns = [
            r for r in resolution.values() if r.context == "group"
        ]
        record.aggregations = sorted(
            {
                f"{agg.sql_name().lower()}({agg.this.sql().lower()})"
                for agg in analyzed.find_all(exp.AggFunc)
                if agg.this is not None
            }
        )
        record.ctes = _extract_ctes(analyzed, stmt.file, stmt.stmt_index)
    except Exception as exc:  # noqa: BLE001 - keep partial result, never crash run
        record.error = f"extract: {type(exc).__name__}: {exc}"
    return record


def extract_all(
    statements: list[ParsedStatement],
    catalog: dict[str, set[str]] | None = None,
) -> list[QueryRecord]:
    return [extract_record(s, catalog=catalog) for s in statements]
