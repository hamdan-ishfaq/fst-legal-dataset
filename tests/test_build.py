import sqlite3

import pytest

from fstlegal.corpus.build import build, judge_id
from fstlegal.corpus.chunking import MAX_WORDS, statute_chunks


def test_judge_names_share_an_id():
    assert judge_id("Justice (Retd.) Rooh-ul-Amin Khan") == judge_id("Rooh-ul-Amin Khan")
    assert judge_id("Chairman Rooh-ul-Amin Khan") == judge_id("ROOH-UL-AMIN KHAN")


def test_long_statute_unit_is_split_at_subsections():
    text = "\n".join(f"({i}) " + "word " * 120 for i in range(1, 6))
    chunks = statute_chunks("CSA-1973:s-9", "Civil Servants Act, 1973, s-9: Promotion", text)
    assert len(chunks) > 1
    assert all(c.text.startswith("Civil Servants Act") for c in chunks)
    assert all(len(c.text.split()) <= MAX_WORDS + 20 for c in chunks)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    out = tmp_path_factory.mktemp("build") / "corpus.db"
    digest = build(out)
    return out, digest


@pytest.mark.data
def test_build_is_deterministic(corpus, tmp_path):
    _, first = corpus
    assert build(tmp_path / "again.db") == first


@pytest.mark.data
def test_corpus_contents(corpus):
    out, _ = corpus
    con = sqlite3.connect(out)
    q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    assert q("SELECT COUNT(*) FROM judgments") == 28
    assert q("SELECT COUNT(*) FROM statute_units WHERE id='CONST-1973:art-10A'") == 1
    assert q("SELECT COUNT(*) FROM statute_units WHERE act_id='CONST-1973' AND omitted=1") > 0
    # every edge starts at a node that exists
    assert q("""SELECT COUNT(*) FROM edges WHERE src NOT IN (SELECT id FROM judgments)
                AND src NOT IN (SELECT id FROM statute_units)""") == 0
    # full-text search works
    hits = con.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'reinstatement'")
    assert hits.fetchone()[0] > 0
