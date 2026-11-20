"""
Enrich a case in fst.db with the detailed data from the full judgment page.

Usage:
    from enrich_case import enrich

    enrich(
        citation   = "2026 PLC(CS) 1296",   # or use case_id=1
        appeal_number  = "Appeal No.167(P)C.S. of 2022",
        decision_date  = "21st August, 2025",
        bench_members  = ["Rooh-ul-Amin Khan", "Sarwat Tahira Habib"],
        outcome        = "allowed",
        summary        = "...",
        questions      = ["Whether major penalties can be imposed without charge sheet?", ...],
        laws           = [{"provision": "Section 4", "act": "Federal Service Tribunals Act, 1973"}, ...],
        keywords       = ["dismissal from service", "natural justice", "service appeal"],
        precedents     = [{"citation": "2005 SCMR 890", "name": "Managing Director OGDCL v. Syed Najmul Hassan"}, ...],
        connected_appeals = "168(P)CS/2022, 169(P)CS/2022, 170(P)CS/2022, 171(P)CS/2022",
        full_text      = "...",
    )
"""
import os
import sqlite3
import json

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fst.db')


def _get_or_create_judge(con, name):
    name = name.strip()
    con.execute('INSERT OR IGNORE INTO judges(name) VALUES (?)', (name,))
    return con.execute('SELECT id FROM judges WHERE name=?', (name,)).fetchone()[0]


def _get_or_create_law(con, provision, act):
    provision = provision.strip()
    act = act.strip()
    con.execute('INSERT OR IGNORE INTO laws(provision, act) VALUES (?,?)', (provision, act))
    return con.execute('SELECT id FROM laws WHERE provision=? AND act=?',
                       (provision, act)).fetchone()[0]


def enrich(
    citation=None,
    case_id=None,
    appeal_number=None,
    decision_date=None,
    bench_members=None,     # list of name strings
    outcome=None,
    summary=None,
    questions=None,         # list of question strings
    laws=None,              # list of {"provision":..., "act":...}
    keywords=None,          # list of tag strings
    precedents=None,        # list of {"citation":..., "name":...}
    connected_appeals=None,
    full_text=None,
):
    con = sqlite3.connect(DB_FILE)
    con.execute('PRAGMA foreign_keys=ON')

    # Find the case
    if case_id:
        row = con.execute('SELECT id FROM cases WHERE id=?', (case_id,)).fetchone()
    elif citation:
        # Try exact match first, then partial
        row = con.execute('SELECT id FROM cases WHERE citation=?', (citation,)).fetchone()
        if not row:
            # Normalize reporter variations and try again
            row = con.execute(
                'SELECT id FROM cases WHERE citation LIKE ?',
                (f'%{citation.split()[-1]}%',)   # match by page number
            ).fetchone()
    else:
        raise ValueError("Provide citation or case_id")

    if not row:
        raise ValueError(f"Case not found: {citation!r}")
    cid = row[0]

    # Build the update
    fields, vals = [], []

    def add(col, val):
        if val is not None:
            fields.append(f'{col}=?')
            vals.append(val)

    add('appeal_number',   appeal_number)
    add('decision_date',   decision_date)
    add('outcome',         outcome)
    add('summary',         summary)
    add('connected_appeals', connected_appeals)
    add('full_text',       full_text)

    if bench_members is not None:
        add('bench_members', json.dumps(bench_members, ensure_ascii=False))
    if questions is not None:
        add('questions_json', json.dumps(questions, ensure_ascii=False))
    if laws is not None:
        add('laws_json', json.dumps(laws, ensure_ascii=False))
    if keywords is not None:
        add('keywords', ', '.join(keywords))
    if precedents is not None:
        add('precedents_json', json.dumps(precedents, ensure_ascii=False))

    fields.append('enriched=1')
    fields.append("updated_at=datetime('now')")
    vals.append(cid)
    con.execute(f'UPDATE cases SET {", ".join(fields)} WHERE id=?', vals)

    # Populate normalized graph tables
    if bench_members:
        for name in bench_members:
            jid = _get_or_create_judge(con, name)
            con.execute(
                'INSERT OR IGNORE INTO case_judges(case_id, judge_id, role) VALUES (?,?,?)',
                (cid, jid, 'member')
            )

    if laws:
        for law in laws:
            lid = _get_or_create_law(con, law.get('provision', ''), law.get('act', ''))
            con.execute(
                'INSERT OR IGNORE INTO case_laws(case_id, law_id) VALUES (?,?)',
                (cid, lid)
            )

    if precedents:
        for p in precedents:
            con.execute(
                'INSERT OR REPLACE INTO precedents(case_id, cited_citation, cited_name) VALUES (?,?,?)',
                (cid, p.get('citation', ''), p.get('name', ''))
            )

    con.commit()
    con.close()
    print(f"Enriched case id={cid}")


# ---------------------------------------------------------------------------
# Demo: enrich the first case (Zahid Ullah) with the data you pasted
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    enrich(
        citation="2026 PLC(CS) 1296",
        appeal_number="Appeal No.167(P)C.S. of 2022",
        decision_date="21st August, 2025",
        bench_members=["Rooh-ul-Amin Khan", "Sarwat Tahira Habib"],
        outcome="allowed",
        summary=(
            "Service appeal by a Sepoy of Frontier Corps challenging dismissal and one year "
            "rigorous imprisonment for alleged weapons smuggling. FST held disciplinary action "
            "vitiated due to lack of formal charge sheet, denial of right to cross-examine witnesses, "
            "absence of direct evidence, and disparate treatment of co-accused. Appeal accepted; "
            "dismissal order set aside; appellant reinstated; back benefits to be decided within two months."
        ),
        questions=[
            "Whether major penalties of dismissal and imprisonment can be imposed upon Frontier Corps "
            "personnel without issuing a formal charge sheet and providing an opportunity of defense?",
            "Does the imposition of disparate punishments on similarly placed co-accused violate the "
            "fundamental right to equality under Article 25 of the Constitution of Pakistan?",
            "Whether an appeal filed prematurely before a Service Tribunal becomes maintainable if it "
            "matures during the pendency of the proceedings before the Tribunal?",
            "Is a disciplinary action sustainable when it is based solely on uncorroborated inquiry "
            "recommendations without direct or circumstantial evidence linking the accused to the alleged misconduct?",
        ],
        laws=[
            {"provision": "Section 4",    "act": "Federal Service Tribunals Act, 1973"},
            {"provision": "Section 1(3)", "act": "Frontier Corps Ordinance, 1959"},
            {"provision": "Section 8(2)", "act": "Frontier Corps Ordinance, 1959"},
            {"provision": "Section 26",   "act": "Frontier Corps Ordinance, 1959"},
            {"provision": "Article 10-A", "act": "Constitution of Pakistan 1973"},
            {"provision": "Article 25",   "act": "Constitution of Pakistan 1973"},
        ],
        keywords=["dismissal from service", "rigorous imprisonment", "disciplinary proceedings",
                  "right to fair trial", "natural justice", "service appeal", "Frontier Corps",
                  "charge sheet", "cross-examination", "disparate treatment"],
        precedents=[
            {"citation": "2005 SCMR 890",  "name": "Managing Director OGDCL v. Syed Najmul Hassan Naqvi"},
            {"citation": "PLD 2002 SC 800","name": "Government of Pakistan v. Tariq Masood"},
            {"citation": "PLD 2013 SC 1",  "name": "Lt. Col. (R.) Muhammad Akram v. Federation of Pakistan"},
            {"citation": "2020 SCMR 1245", "name": "Chief Secretary Punjab v. Muhammad Ali Saqib"},
            {"citation": "2023 SCMR 1135", "name": "Raja Muhammad Shahid v. IGP"},
            {"citation": "2022 SCMR 1370", "name": "Federation of Pakistan v. Muhammad Javed"},
            {"citation": "2019 SCMR 320",  "name": "Muhammad Farooq v. Federation of Pakistan"},
            {"citation": "PLD 2023 SC 119","name": "Director General FIA v. Muhammad Zubair"},
        ],
        connected_appeals="168(P)CS/2022, 169(P)CS/2022, 170(P)CS/2022, 171(P)CS/2022",
    )

    import sqlite3 as _s
    con = _s.connect(DB_FILE)
    print("\n--- enriched case ---")
    row = con.execute('SELECT id,case_name,outcome,enriched,keywords FROM cases WHERE id=1').fetchone()
    print(row)
    print("\n--- judges table ---")
    for r in con.execute('SELECT * FROM judges'):
        print(r)
    print("\n--- laws table (first 5) ---")
    for r in con.execute('SELECT * FROM laws LIMIT 5'):
        print(r)
    print("\n--- precedents table ---")
    for r in con.execute('SELECT * FROM precedents WHERE case_id=1'):
        print(r)
