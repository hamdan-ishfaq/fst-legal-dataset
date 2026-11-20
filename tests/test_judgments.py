from pathlib import Path

import pytest

from fstlegal.corpus.citations import citation_key
from fstlegal.corpus.judgments import load_judgments, looks_truncated, split_paragraphs

CLEAN_CSV = Path(__file__).parents[1] / "dataset" / "fst_cases_clean.csv"


def test_paragraphs_follow_the_numbering():
    text = ("Opening text. 2. Facts of the case are (1) one and 3. three. "
            "3. The appellant argued. 4. Appeal dismissed.")
    paras = split_paragraphs(text)
    assert [p.number for p in paras] == [1, 2, 3, 4]
    assert paras[1].text.startswith("2. Facts")


def test_numbered_list_inside_a_paragraph_is_not_a_break():
    text = "Opening. 2. The rules say: 7. something unrelated. 3. Next paragraph."
    assert [p.number for p in split_paragraphs(text)] == [1, 2, 3]


@pytest.mark.parametrize("ending, truncated", [
    ("The appeal is, therefore, dismissed. 8. No order as to costs. Parties be informed.", False),
    ("the appeal at hand is beyond the jurisdiction and stands dismissed for want of it.", False),
    ("this is not an absolute rule. Where", True),
    ("which is d fundamental right as envisaged under Article 10-A", True),
])
def test_truncation_heuristic(ending, truncated):
    assert looks_truncated("Some long judgment text. " * 50 + ending) is truncated


@pytest.mark.parametrize("a, b", [
    ("2020 PLC (C.S.) 123", "2020 PLC(CS) 123"),
    ("2019 SCM R 45", "2019 SCMR 45"),
    ("PLD 1999 S.C. 10", "PLD 1999 Supreme Court 10"),
    ("2023 PLJ Tr. C. (Service) 111", "2023 PLJ Tr.C. (Services) 111"),
])
def test_citation_spellings_share_a_key(a, b):
    assert citation_key(a) == citation_key(b)


@pytest.mark.data
def test_clean_dataset_loads():
    judgments = load_judgments(CLEAN_CSV)
    assert len({j.site_id for j in judgments}) == len(judgments)
    complete = [j for j in judgments if not j.text_truncated]
    assert all(j.paragraphs for j in judgments)
    # the ruling is found for nearly every complete judgment
    assert sum(bool(j.operative_order) for j in complete) >= 0.9 * len(complete)
