import pytest

from fstlegal.pipeline.closed_book import Resolver
from fstlegal.retrieval.store import Corpus


@pytest.mark.data
def test_resolver_maps_written_citations_to_corpus_ids():
    corpus = Corpus()
    resolve = Resolver(corpus)
    assert resolve("Section 4, Service Tribunals Act, 1973") == "STA-1973:s-4"
    assert resolve("Article 212 of the Constitution") == "CONST-1973:art-212"
    jid = corpus.judgment_ids()[0]
    assert resolve(f"see {corpus.judgment(jid)['citations'][0]}") == jid
    assert resolve("Section 999, Imaginary Act, 2001") is None
