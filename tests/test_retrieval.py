import pytest

from fstlegal.eval.retrieval_eval import mrr, ndcg_at, recall_at
from fstlegal.retrieval.hybrid import rrf
from fstlegal.retrieval.lexical import fts_query


def test_fts_query_quotes_terms_and_drops_stopwords():
    q = fts_query('Whether the "appeal" is time-barred under Article 212? OR NEAR(x)')
    assert q == '"appeal" OR "time" OR "barred" OR "article" OR "212" OR "near"'


def test_fts_query_of_only_stopwords_is_empty():
    assert fts_query("whether the of and") == ""


def test_rrf_rewards_agreement():
    fused = dict(rrf([["a", "b", "c"], ["b", "a", "d"]]))
    assert fused["a"] == fused["b"]
    assert fused["a"] > fused["c"] > 0
    assert fused["c"] == fused["d"]


def test_metrics():
    ranked = ["x", "a", "y", "b"]
    gold = {"a", "b"}
    assert recall_at(ranked, gold, 2) == 0.5
    assert recall_at(ranked, gold, 4) == 1.0
    assert mrr(ranked, gold) == 0.5
    assert 0 < ndcg_at(ranked, gold, 10) < 1
    assert ndcg_at(["a", "b"], gold, 10) == pytest.approx(1.0)


@pytest.fixture(scope="module")
def retriever():
    from fstlegal.corpus.build import DEFAULT_OUT
    if not DEFAULT_OUT.exists():
        pytest.skip("corpus.db not built")
    from fstlegal.retrieval.hybrid import Retriever
    from fstlegal.retrieval.store import Corpus
    return Retriever(Corpus(DEFAULT_OUT), mode="bm25+graph")


@pytest.mark.data
def test_statute_search_finds_fair_trial_article(retriever):
    hits = [r.id for r in retriever.search_statutes("right to fair trial and due process", k=10)]
    assert "CONST-1973:art-10A" in hits


@pytest.mark.data
def test_hidden_judgment_is_never_returned(retriever):
    jid = retriever.corpus.judgment_ids()[0]
    question = retriever.corpus.judgment(jid)["questions"][0]
    assert jid not in [r.id for r in retriever.search_cases(question, k=20, exclude={jid})]


@pytest.mark.data
def test_case_results_carry_passages(retriever):
    results = retriever.search_cases("dismissal from service without inquiry", k=5)
    assert results and all(r.passages for r in results[:3])
