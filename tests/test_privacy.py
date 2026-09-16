from __future__ import annotations

import pytest

from sqlinsight import cli


@pytest.mark.parametrize("literal", [
    "'{secret}'", "E'prefix\\'{secret}'", "$$prefix'{secret}$$",
])
def test_artifacts_do_not_persist_literals_or_absolute_source_paths(tmp_path, literal):
    secret = "literal-secret-7f3a9b"
    corpus = tmp_path / "private" / "corpus"
    corpus.mkdir(parents=True)
    query = f"""
    with sensitive as (
        select customer_id, sum(amount) as total
        from sales.orders
        where access_token = {literal.format(secret=secret)}
        group by customer_id
    )
    select * from sensitive
    """
    (corpus / "a.sql").write_text(query, encoding="utf-8")
    (corpus / "b.sql").write_text(query, encoding="utf-8")
    (corpus / "broken.sql").write_text(
        f"select from where access_token = '{secret}'", encoding="utf-8"
    )
    out = tmp_path / "out"

    assert cli.run(str(corpus.resolve()), str(out)) == 0
    absolute_source = str(corpus.resolve()).encode()
    for artifact in out.iterdir():
        content = artifact.read_bytes()
        assert secret.encode() not in content, f"literal leaked into {artifact.name}"
        assert absolute_source not in content, f"absolute path leaked into {artifact.name}"
