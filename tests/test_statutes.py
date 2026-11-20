import pytest

from fstlegal.corpus.sources import STATUTES
from fstlegal.corpus.statutes import _heading_continues, _unit_start, parse_statute


@pytest.mark.parametrize("line, last, expected", [
    ("4. Appeals to tribunals.—(1) Any civil servant", 3, ("4", "Appeals to tribunals")),
    ("1[4A. Review.⎯ (1) A tribunal shall", 4, ("4A", "Review")),
    ("2. Definitions.__ (1) In this Act", 1, ("2", "Definitions")),
    ("26. 2[Omitted]", 25, ("26", "Omitted")),
    ("(2) It shall come into force at once.", 1, None),
    ("5. Powers of Tribunals.—(1)", 9, None),  # out of sequence
])
def test_unit_start(line, last, expected):
    found = _unit_start(line, last, "")
    assert (found[:2] if found else None) == expected


def test_wrapped_heading_is_joined():
    assert _heading_continues("9. Procedure to be followed by authority where inquiry is",
                              "necessary.—(1) Where the authority decides")
    assert not _heading_continues("4. Penalties.—(1) The authority may", "next line")


@pytest.fixture(scope="module")
def parsed():
    return {s.act_id: parse_statute(s.path, s.act_id, s.header, s.noise, s.unnumbered_headings)
            for s in STATUTES}


@pytest.mark.data
@pytest.mark.parametrize("act_id, expected", [
    ("STA-1973", ["1", "2", "3", "3A", "4", "4A", "5", "5A", "6", "7", "8"]),
    ("ED-2020", [str(n) for n in range(1, 22)]),
])
def test_all_units_found(parsed, act_id, expected):
    assert [u.number for u in parsed[act_id]] == expected


@pytest.mark.data
def test_civil_servants_act(parsed):
    units = {u.number: u for u in parsed["CSA-1973"]}
    assert units["13"].title == "Retirement from service"
    assert units["2"].chapter == "I"
    assert units["26"].omitted
    assert "pleasure" in units["4"].text and "President" in units["4"].text
