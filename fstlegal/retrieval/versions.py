"""Which law a judgment was decided under, and what changed after it.

A judgment decided on date d applied the wording in force on d. For each
provision it applied, this lists the later changes: amendments to that
provision and the repeal of its whole set of rules. With each change come the
judgments decided after it that applied the changed provision (or its
replacement), so a lawyer can see whether the new wording has been tested.
An empty list means no judgment in the corpus has applied it yet.

A judgment may also apply rules that were already repealed when it was
decided: proceedings begun under the old rules usually continue under them
(ED-2020, rule 21(2)). That is reported too, marked ``before_decision``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .store import Corpus


@dataclass
class LawChange:
    unit_id: str
    kind: str  # an amendment kind ("substituted", ...) or "replaced"
    on: str  # ISO date, or a year when only the year is printed
    instrument: str
    note: str
    later_judgments: list[str] = field(default_factory=list)
    before_decision: bool = False  # the change predates the judgment that applied the old law


def _after(on: str, decided: str) -> bool:
    """Whether a change on ``on`` (ISO date or year) may postdate ``decided``.
    A change dated only by the year of the decision counts as after it, since
    it may be."""
    return on > decided if len(on) == 10 else int(on) >= int(decided[:4])


def _decided_after(corpus: Corpus, units: list[str], on: str) -> list[str]:
    since = on if len(on) == 10 else f"{on}-01-01"
    marks = ",".join("?" * len(units))
    rows = corpus.con.execute(
        f"SELECT DISTINCT j.id FROM edges e JOIN judgments j ON j.id = e.src "
        f"WHERE e.rel = 'APPLIES' AND e.dst IN ({marks}) AND j.decision_date >= ? "
        f"ORDER BY j.decision_date, j.id", (*units, since))
    return [r[0] for r in rows]


def changes_since(corpus: Corpus, unit_id: str, decided: str) -> list[LawChange]:
    """Changes to ``unit_id`` after ``decided`` (ISO date), and the repeal of its rules
    at any time, oldest first."""
    changes = []
    for row in corpus.con.execute(
            "SELECT kind, instrument, COALESCE(effective, date) AS on_date, year, note "
            "FROM amendments WHERE unit_id = ?", (unit_id,)):
        on = row["on_date"] or (str(row["year"]) if row["year"] else None)
        if on and _after(on, decided):
            changes.append(LawChange(unit_id, row["kind"], on, row["instrument"], row["note"],
                                     _decided_after(corpus, [unit_id], on)))
    act = corpus.con.execute(
        "SELECT a.replaced_by, a.replaced_on, n.title FROM statute_units u "
        "JOIN acts a ON a.id = u.act_id LEFT JOIN acts n ON n.id = a.replaced_by "
        "WHERE u.id = ?", (unit_id,)).fetchone()
    if act and act["replaced_by"]:
        new_units = [r[0] for r in corpus.con.execute(
            "SELECT id FROM statute_units WHERE act_id = ?", (act["replaced_by"],))]
        changes.append(LawChange(
            unit_id, "replaced", act["replaced_on"], act["replaced_by"],
            f"Repealed and replaced by the {act['title']}",
            _decided_after(corpus, new_units + [act["replaced_by"]], act["replaced_on"]),
            before_decision=not _after(act["replaced_on"], decided)))
    return sorted(changes, key=lambda c: c.on)


def judgment_law_changes(corpus: Corpus, judgment_id: str) -> list[LawChange]:
    """Changes after the judgment to every provision it applied."""
    j = corpus.judgment(judgment_id)
    if not j or not j["decision_date"]:
        return []
    units = [r[0] for r in corpus.con.execute(
        "SELECT e.dst FROM edges e JOIN statute_units u ON u.id = e.dst "
        "WHERE e.src = ? AND e.rel = 'APPLIES' ORDER BY e.dst", (judgment_id,))]
    return [c for u in units for c in changes_since(corpus, u, j["decision_date"])]


def describe(corpus: Corpus, change: LawChange, decided: str) -> str:
    """One plain sentence on a change, for the brief."""
    unit = corpus.unit(change.unit_id)
    provision = f"{change.unit_id.split(':')[1]} of the {corpus.act_title(unit['act_id'])}"
    if change.kind == "replaced":
        when = ("had already been replaced on {on}; proceedings begun under the old rules "
                "continue under them" if change.before_decision else "were replaced on {on}")
        text = (f"Decided {decided} under {provision}. Those rules "
                + when.format(on=change.on) + f" by the {corpus.act_title(change.instrument)}.")
    else:
        text = (f"Decided {decided} under {provision}, which was {change.kind} on {change.on}"
                + (f" ({change.instrument})" if change.instrument else "") + ".")
    if change.later_judgments:
        later = ", ".join(change.later_judgments[:5])
        return f"{text} Judgments applying the new wording since: {later}."
    return f"{text} No judgment in the corpus has applied the new wording yet."
