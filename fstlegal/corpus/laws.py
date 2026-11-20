"""Canonical acts and provision references.

The enrichment step stores each law reference as a free-text
``{"provision": ..., "act": ...}`` pair. The same act appears under many
spellings, and the scraper sometimes split a name across both fields or left
only the year in ``act``. This module maps any such pair to a canonical act
and to statute-unit IDs such as ``CONST-1973:art-10A`` or ``CSA-1973:s-13``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Act:
    id: str
    title: str
    unit_kind: str  # "art", "s", "r" or "fr": what a numbered unit is called in this act
    patterns: tuple[str, ...]  # regexes, all must match the lower-cased reference text
    core: bool = False  # full text is ingested into the corpus


# Order matters: more specific acts come first.
ACTS: tuple[Act, ...] = (
    Act("KPST-1974", "North-West Frontier Province Service Tribunals Act, 1974", "s",
        (r"(frontier province|n\.?w\.?f\.?p|khyber)", r"tribunal")),
    Act("STPR-1974", "Service Tribunals (Procedure) Rules, 1974", "r",
        (r"tribunals?\s*\(procedure\)",), core=True),
    Act("STA-1973", "Service Tribunals Act, 1973", "s",
        (r"services?\s+tribunals?\s+act",), core=True),
    Act("CS-APPEAL-1977", "Civil Servants (Appeal) Rules, 1977", "r",
        (r"civil servants\s*\(appeal\)",), core=True),
    Act("CS-APT-1973", "Civil Servants (Appointment, Promotion and Transfer) Rules, 1973", "r",
        (r"(appointment|promotion and transfer)",), core=True),
    Act("CS-SEN-1993", "Civil Servants (Seniority) Rules, 1993", "r",
        (r"civil servants\s*\(seniority\)",), core=True),
    Act("WAPDA-ED-1978", "Pakistan WAPDA Employees (Efficiency and Discipline) Rules, 1978", "r",
        (r"wapda",)),
    Act("ED-2020", "Civil Servants (Efficiency and Discipline) Rules, 2020", "r",
        (r"(efficiency\s*(and|&)\s*discipline|e\s*&\s*d)", r"2020"), core=True),
    Act("ED-1973", "Government Servants (Efficiency and Discipline) Rules, 1973", "r",
        (r"(efficiency\s*(and|&)\s*discipline|e\s*&\s*d)",), core=True),
    Act("PSP-CCS-1985", "Police Service of Pakistan (Composition, Cadre and Seniority) Rules, 1985",
        "r", (r"police service of pakistan",)),
    Act("CONST-1973", "Constitution of the Islamic Republic of Pakistan, 1973", "art",
        (r"constitution",), core=True),
    Act("CSA-1973", "Civil Servants Act, 1973", "s", (r"civil servants act",), core=True),
    Act("CPC-1908", "Code of Civil Procedure, 1908", "s", (r"civil procedure",)),
    Act("PPC-1860", "Pakistan Penal Code, 1860", "s", (r"penal code",)),
    Act("GCA-1897", "General Clauses Act, 1897", "s", (r"general clauses",)),
    Act("LIM-1908", "Limitation Act, 1908", "s", (r"limitation act",)),
    Act("PAA-1952", "Pakistan Army Act, 1952", "s", (r"army act",)),
    Act("FCO-1959", "Frontier Corps Ordinance, 1959", "s", (r"frontier corps",)),
    Act("WPRO-1959", "West Pakistan Rangers Ordinance, 1959", "s", (r"rangers",)),
    Act("CUSTOMS-1969", "Customs Act, 1969", "s", (r"customs act",)),
    Act("FPSC-1977", "Federal Public Service Commission Ordinance, 1977", "s",
        (r"public service commission",)),
    Act("ROB-1973", "Rules of Business, 1973", "r", (r"rules of business",)),
    Act("FR", "Fundamental Rules", "fr", (r"fundamental rules?",)),
    Act("CSR", "Civil Service Regulations", "art", (r"civil service regulations",)),
    Act("PN-WORKMEN-1965",
        "Rules Relating to Workmen of PN Dockyard and other PN Establishments, 1965", "r",
        (r"pn dockyard",)),
)

ACTS_BY_ID = {a.id: a for a in ACTS}

_UNIT_WORDS = r"(?:fundamental\s+rules?|articles?|sections?|rules?|regulations?|arts?\.|ss?\.)"
# Up to three digits, so the year in "Rules, 1973" is not read as rule 1973.
_NUMBER = r"\d{1,3}(?!\d)(?:-?[A-Z]{1,2})?"
_SUBPARTS = r"(?:\s*\([0-9a-zA-Z]{1,5}\))*"
_UNIT_RE = re.compile(
    rf"(?:{_UNIT_WORDS})\s*(?P<num>{_NUMBER})(?P<sub>{_SUBPARTS})", re.IGNORECASE)
_LIST_RE = re.compile(rf"(?:,|\band\b|&)\s*(?P<num>{_NUMBER})(?P<sub>{_SUBPARTS})", re.IGNORECASE)
_RANGE_RE = re.compile(rf"(?P<a>{_NUMBER})\s+to\s+(?P<b>{_NUMBER})", re.IGNORECASE)
_ORDER_RE = re.compile(r"order\s+(?P<order>[IVXLC]+)\s+rule\s+(?P<rule>\d+)", re.IGNORECASE)


@dataclass
class LawRef:
    """One resolved law reference from a judgment."""

    raw: str
    act_id: str | None
    unit_ids: list[str] = field(default_factory=list)
    subrefs: list[str] = field(default_factory=list)  # e.g. "(3)" for Article 212(3)
    range_end: str | None = None  # set for "Sections 20 to 24A"

    @property
    def resolved(self) -> bool:
        return self.act_id is not None and bool(self.unit_ids)


def resolve_act(text: str) -> Act | None:
    t = text.lower()
    for act in ACTS:
        if all(re.search(p, t) for p in act.patterns):
            return act
    return None


def normalize_number(num: str) -> str:
    """'10-A' -> '10A', '6-a' -> '6A'."""
    return num.replace("-", "").upper()


def unit_id(act: Act, num: str) -> str:
    return f"{act.id}:{act.unit_kind}-{normalize_number(num)}"


def resolve(provision: str, act_text: str) -> LawRef:
    """Resolve one ``laws_json`` entry. Both fields are read together because
    the scraper sometimes put the act name in ``provision``."""
    raw = f"{provision or ''} | {act_text or ''}".strip(" |")
    combined = f"{provision or ''} {act_text or ''}"
    act = resolve_act(combined)
    ref = LawRef(raw=raw, act_id=act.id if act else None)
    if act is None:
        return ref

    order = _ORDER_RE.search(combined)
    if order:
        ref.unit_ids.append(f"{act.id}:o-{order['order'].upper()}-r-{order['rule']}")
        return ref

    m = _UNIT_RE.search(provision or "")
    if not m:
        return ref
    ref.unit_ids.append(unit_id(act, m["num"]))
    ref.subrefs.append(m["sub"].replace(" ", ""))

    rest = (provision or "")[m.end():]
    rng = _RANGE_RE.match(f"{m['num']}{rest}".replace("  ", " "))
    if rng:
        ref.range_end = unit_id(act, rng["b"])
        return ref
    for extra in _LIST_RE.finditer(rest):
        ref.unit_ids.append(unit_id(act, extra["num"]))
        ref.subrefs.append(extra["sub"].replace(" ", ""))
    return ref
