import pytest

from fstlegal.corpus.outcomes import normalize_outcome


@pytest.mark.parametrize("raw, label", [
    ("allowed", "allowed"),
    ("Appeal accepted.", "allowed"),
    ("dismissed", "dismissed"),
    ("Appeal disposed of.", "disposed_of"),
    ("Order Accordingly.", "disposed_of"),
    ("Appeal partly allowed.", "partly_allowed"),
    ("Case remanded to the department.", "remanded"),
    ("Appeal dismissed as withdrawn.", "withdrawn"),
    ("Appeal dismissed being not maintainable.", "dismissed"),
    ("", "unknown"),
    (None, "unknown"),
    ("Adjourned", "unknown"),
])
def test_normalize_outcome(raw, label):
    assert normalize_outcome(raw) == label
