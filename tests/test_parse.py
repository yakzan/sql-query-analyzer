from sqlinsight.parse import PRIMARY_DIALECT, parse_file


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
