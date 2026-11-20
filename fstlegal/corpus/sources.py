"""Where each statute text comes from and how to parse it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "data" / "sources"
CLEAN_JUDGMENTS = ROOT / "dataset" / "fst_cases_clean.csv"
CONSTITUTION_PDF = SOURCES / "constitution" / "constitution_27th_amendment.pdf"

_GAZETTE_NOISE = re.compile(r"GAZETTE OF PAK|^\d{4}$|^\(\d{4}\)$|^Price: |Ex\. Gaz\.\]$")


@dataclass(frozen=True)
class StatuteSource:
    act_id: str
    path: Path
    header: str  # running title printed on each page
    edition: str
    noise: re.Pattern | None = None
    unnumbered_headings: bool = False


STATUTES: tuple[StatuteSource, ...] = (
    StatuteSource("STA-1973", SOURCES / "statutes" / "service_tribunals_act_1973.pdf",
                  "THE SERVICE TRIBUNALS ACT, 1973", "Pakistan Code, updated till 3.8.2022"),
    StatuteSource("CSA-1973", SOURCES / "statutes" / "civil_servants_act_1973.pdf",
                  "THE CIVIL SERVANTS ACT, 1973", "Pakistan Code, dated 26.10.2026"),
    StatuteSource("ED-2020", SOURCES / "statutes" / "ed_rules_2020_gazette.pdf",
                  "", "Gazette of Pakistan, Extraordinary, 11 December 2020 (S.R.O. 1331(I)/2020)",
                  noise=_GAZETTE_NOISE, unnumbered_headings=True),
)
