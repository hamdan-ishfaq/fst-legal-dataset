import pytest

from fstlegal.corpus.laws import resolve


@pytest.mark.parametrize("provision, act, expected_act, expected_units", [
    ("Article 10-A", "Constitution of Pakistan 1973", "CONST-1973", ["CONST-1973:art-10A"]),
    ("Article 10A", "Constitution of Islamic Republic of Pakistan 1973", "CONST-1973",
     ["CONST-1973:art-10A"]),
    ("Section 4", "Services Tribunal Act 1973", "STA-1973", ["STA-1973:s-4"]),
    ("Section 4", "Federal Service Tribunals Act, 1973", "STA-1973", ["STA-1973:s-4"]),
    # wrong unit word in the source: the act decides the unit kind
    ("Rule 4(1)(b)", "Service Tribunals Act 1973", "STA-1973", ["STA-1973:s-4"]),
    ("Section 5", "Government Servants (E&D) Rules 1973", "ED-1973", ["ED-1973:r-5"]),
    ("Rule 6-A", "Government Servants (Efficiency and Discipline) Rules, 1973", "ED-1973",
     ["ED-1973:r-6A"]),
    ("Civil Servants (Efficiency & Discipline) Rules", "2020", "ED-2020", []),
    ("Rule 21", "Service Tribunals (Procedure) Rules, 1974", "STPR-1974", ["STPR-1974:r-21"]),
    ("Sections 1(3) and 3(2)", "Federal Service Tribunal Act 1973", "STA-1973",
     ["STA-1973:s-1", "STA-1973:s-3"]),
    ("Order XXXIX Rule 2", "Code of Civil Procedure 1908", "CPC-1908", ["CPC-1908:o-XXXIX-r-2"]),
    ("Fundamental Rule 9(25)", "Fundamental Rules", "FR", ["FR:fr-9"]),
    ("Article 371-A", "Civil Service Regulations", "CSR", ["CSR:art-371A"]),
    ("Section 4(1)(b)(i)", "North West Frontier Province Service Tribunal Act, 1974",
     "KPST-1974", ["KPST-1974:s-4"]),
    # name split across both fields by the scraper
    ("Civil Servants (Appointment", "Promotion and Transfer) Rules, 1973", "CS-APT-1973", []),
    ("Civil Servants Act", "1973", "CSA-1973", []),
    # the year is not a rule number
    ("Government Servants (Efficiency and Discipline) Rules, 1973", "", "ED-1973", []),
])
def test_resolve(provision, act, expected_act, expected_units):
    ref = resolve(provision, act)
    assert ref.act_id == expected_act
    assert ref.unit_ids == expected_units


def test_subreference_is_kept():
    ref = resolve("Article 212(3)", "Constitution of Pakistan 1973")
    assert ref.unit_ids == ["CONST-1973:art-212"]
    assert ref.subrefs == ["(3)"]


def test_range():
    ref = resolve("Sections 20 to 24A", "Code of Civil Procedure 1908")
    assert ref.unit_ids == ["CPC-1908:s-20"]
    assert ref.range_end == "CPC-1908:s-24A"


def test_unknown_act():
    assert resolve("Section 3", "Some Unknown Act 2001").act_id is None
