from sqlglot import exp

from sqlinsight.parse import PRIMARY_DIALECT, parse_all, parse_file


def test_parse_file_keeps_valid_statements_when_one_is_malformed(tmp_path):
    path = tmp_path / "mixed.sql"
    path.write_text("select 1; select from ; select 2;", encoding="utf-8")

    rows = parse_file(path)
    assert len(rows) == 3
    assert [r.expression is not None for r in rows] == [True, False, True]
    assert rows[1].dialect == PRIMARY_DIALECT
    assert rows[1].error.startswith("ParseError:")


def test_parse_file_ignores_empty_segments_between_semicolons(tmp_path):
    path = tmp_path / "empty_segments.sql"
    path.write_text("select 1;;  ;select 2;", encoding="utf-8")

    rows = parse_file(path)
    assert [r.stmt_index for r in rows] == [0, 1]


def test_parse_file_resolves_static_dbt_relation_macros(tmp_path):
    path = tmp_path / "model.sql"
    path.write_text(
        "{{ config(materialized='table') }}\n"
        "select * from {{ source('raw', 'orders') }} o "
        "join {{ ref('customers') }} c on o.customer_id = c.customer_id",
        encoding="utf-8",
    )

    row = parse_file(path)[0]
    tables = sorted(exp.table_name(t) for t in row.expression.find_all(exp.Table))
    assert tables == ["customers", "raw.orders"]


def test_parse_error_does_not_include_source_sql(tmp_path):
    path = tmp_path / "broken.sql"
    path.write_text("select from where password = 'private-value'", encoding="utf-8")

    row = parse_file(path)[0]
    assert row.expression is None
    assert "private-value" not in row.error
    assert "line 1" in row.error


def test_parse_all_uses_portable_paths_for_absolute_source(tmp_path):
    corpus = tmp_path / "corpus"
    nested = corpus / "nested"
    nested.mkdir(parents=True)
    (nested / "query.sql").write_text("select 1", encoding="utf-8")

    row = parse_all(corpus.resolve())[0]
    assert row.file == "corpus/nested/query.sql"
    assert str(tmp_path) not in row.file


def test_parse_error_redacts_literal_marker(tmp_path):
    marker = "literal-marker-9d12b7"
    path = tmp_path / "invalid.sql"
    path.write_text(f"select from where status = '{marker}'", encoding="utf-8")

    error = parse_file(path)[0].error
    assert marker not in error
    assert error.startswith("ParseError: unable to parse SQL at line 1, column ")
