import pytest

from fstlegal.corpus import sources
from fstlegal.corpus.amendments import parse_amendment
from fstlegal.corpus.estacode import _footnotes, parse_estacode
from fstlegal.retrieval.store import Corpus
from fstlegal.retrieval.versions import changes_since, judgment_law_changes


@pytest.mark.parametrize("note, kind, instrument, made, effective, year", [
    ("* Subs. vide Establishment Division Notification S.R.O. No. 742(I)/2002, "
     "dated 28-10-2002.", "substituted", "S.R.O. No. 742(I)/2002", "2002-10-28", None, 2002),
    ("Subs. vide Estt. Div.'s Notification S.R.O. No.1(I)/2003, dated 1-1-2003 "
     "w.e.f. 23.11.2002.", "substituted", "S.R.O. No.1(I)/2003", "2003-01-01", "2002-11-23", 2003),
    ("Inserted vide Estab. Div. Notification No. 3/54/2006-R.2, dated the 3rd May, 2007.",
     "inserted", "Notification No. 3/54/2006-R.2", "2007-05-03", None, 2007),
    ("1 Subs. by the Service Tribunals (Amdt.) Act, 1997 (XVII of 1997), s. 2.",
     "substituted", "Service Tribunals (Amdt.) Act, 1997 (XVII of 1997)", None, None, 1997),
    ("2 Ins. by Ord. No. XXI of 1985, s. 2.", "inserted", "Ord. No. XXI of 1985", None, None, 1985),
    ("Omitted clause (f) vide Estt. Div.'s Notification SRO No. 146(I)/84, dated 9-2-1984.",
     "omitted", "SRO No. 146(I)/84", "1984-02-09", None, 1984),
])
def test_parse_amendment(note, kind, instrument, made, effective, year):
    a = parse_amendment(note)
    assert (a.kind, a.instrument, a.date, a.effective, a.year) == (
        kind, instrument, made, effective, year)


def test_explanatory_note_is_not_an_amendment():
    assert parse_amendment("Now Prime Minister.") is None


def test_footnote_markers_and_continuations():
    notes = _footnotes(["* Subs. vide S.R.O. 1/2000,", "dated 1-1-2000.",
                        "** Added vide S.R.O. 2/2001.", "Omitted vide S.R.O. 3/2002."])
    assert notes == [("*", "Subs. vide S.R.O. 1/2000, dated 1-1-2000."),
                     ("**", "Added vide S.R.O. 2/2001."),
                     (None, "Omitted vide S.R.O. 3/2002.")]


@pytest.fixture(scope="module")
def estacode():
    return {s.act_id: parse_estacode(sources.ESTACODE_PDF, s.act_id, s.first_page, s.last_page)
            for s in sources.ESTACODE_RULES}


@pytest.mark.data
@pytest.mark.parametrize("act_id, expected", [
    ("CS-APT-1973", ["1", "2", "3", "4", "5", "6", "7", "7A", "8", "8A", "8B", "9", "10", "11",
                     "12", "12A", "13", "14", "15", "16", "17", "18", "19", "20", "20A", "21"]),
    ("CS-SEN-1993", ["1", "2", "3", "4", "4A", "5", "6", "7"]),
    ("CS-APPEAL-1977", [str(n) for n in range(1, 11)]),
    ("STPR-1974", [str(n) for n in range(1, 24)] + ["23A"] + [str(n) for n in range(24, 28)]),
])
def test_estacode_rules_found(estacode, act_id, expected):
    assert [u.number for u in estacode[act_id].units] == expected


@pytest.mark.data
def test_estacode_amendments_attach_to_their_rule(estacode):
    rules = {u.number: u for u in estacode["CS-APT-1973"].units}
    assert any("742(I)/2002" in n for n in rules["3"].footnotes)
    assert estacode["CS-APT-1973"].authority.endswith("dated 20-10-1973")


@pytest.mark.data
def test_repealed_rules_are_reported():
    corpus = Corpus()
    changes = judgment_law_changes(corpus, "J-190135")
    replaced = [c for c in changes if c.kind == "replaced"]
    assert replaced and replaced[0].instrument == "ED-2020"
    assert replaced[0].before_decision  # decided 2022 under the 1973 rules


@pytest.mark.data
def test_amendments_after_an_early_decision():
    corpus = Corpus()
    changes = changes_since(corpus, "CS-APT-1973:r-3", "1990-01-01")
    assert [c.on for c in changes] == sorted(c.on for c in changes)
    assert any(c.on == "2002-10-28" for c in changes)
    assert not changes_since(corpus, "CS-APT-1973:r-3", "2026-01-01")
