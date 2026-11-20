import re
from pathlib import Path

import pytest

from fstlegal.corpus.constitution import _article_start, parse_constitution

PDF = Path(__file__).parents[1] / "data" / "sources" / "constitution" / \
    "constitution_27th_amendment.pdf"


@pytest.mark.parametrize("line, last, expected", [
    ("212. (1) Notwithstanding anything", 211, "212"),
    ("11. (1) Pakistan shall be", 0, "1"),  # footnote 1 printed before Article 1
    ("10[2A. The principles", 2, "2A"),  # inserted Article with its footnote
    ("1272. Notwithstanding", 271, "272"),
    ("170.1[(1)] The accounts", 169, "170"),
    ("(3) The Commissioner shall", 213, None),
    ("2. The rules say", 150, None),  # a list item, not the next Article
])
def test_article_start(line, last, expected):
    found = _article_start(line, last)
    assert (found[0] if found else None) == expected


@pytest.fixture(scope="module")
def articles():
    return {a.number: a for a in parse_constitution(PDF)}


@pytest.mark.data
def test_every_article_number_is_found(articles):
    numbers = {int(re.match(r"\d+", n).group()) for n in articles}
    assert numbers == set(range(1, 281))


@pytest.mark.data
@pytest.mark.parametrize("number, title", [
    ("4", "Right of individuals to be dealt with in accordance with law, etc."),
    ("10A", "Right to fair trial."),
    ("25", "Equality of citizens."),
    ("212", "Administrative Courts and Tribunals."),
    ("240", "Appointments to service of Pakistan and conditions of service."),
])
def test_titles_from_the_margin(articles, number, title):
    assert articles[number].title == title


@pytest.mark.data
def test_service_tribunal_article_text(articles):
    art = articles["212"]
    assert art.part == "VII"
    assert "terms and conditions of persons" in art.text
    assert not art.omitted


@pytest.mark.data
def test_omitted_article(articles):
    assert articles["184"].omitted
    assert articles["184"].title == "Original Jurisdiction of Supreme Court."
