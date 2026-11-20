"""
Build FST judgment database from raw listing text.
Schema is designed for GraphRAG: normalized judges, laws, precedents tables
so each relationship becomes a graph edge later.

Usage: python build_db.py
"""
import re
import sqlite3
import os

HERE     = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(HERE, '..', 'New Text Document.txt')
DB_FILE  = os.path.join(HERE, 'fst.db')

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS cases (
    id              INTEGER PRIMARY KEY,
    case_name       TEXT,
    petitioner      TEXT,
    respondent      TEXT,
    citation        TEXT,
    year            INTEGER,
    reporter        TEXT,
    page            TEXT,
    court           TEXT DEFAULT 'Federal Service Tribunal',
    notes           TEXT DEFAULT '',

    -- enrichment columns (Step 2 — populated later)
    appeal_number   TEXT,
    decision_date   TEXT,
    bench_members   TEXT,   -- JSON array: ["Name1","Name2"]
    outcome         TEXT,   -- 'allowed' | 'dismissed' | 'partly allowed' | ...

    summary         TEXT,
    questions_json  TEXT,   -- JSON array of question strings
    laws_json       TEXT,   -- JSON array of {"provision":"...","act":"..."}
    keywords        TEXT,   -- comma-separated tags
    precedents_json TEXT,   -- JSON array of {"citation":"...","name":"..."}
    connected_appeals TEXT,
    full_text       TEXT,

    enriched        INTEGER DEFAULT 0,
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now'))
);

-- Graph nodes: judges
CREATE TABLE IF NOT EXISTS judges (
    id              INTEGER PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL
);

-- Graph edges: case <-> judge
CREATE TABLE IF NOT EXISTS case_judges (
    case_id  INTEGER NOT NULL REFERENCES cases(id),
    judge_id INTEGER NOT NULL REFERENCES judges(id),
    role     TEXT,   -- 'presiding' | 'member'
    PRIMARY KEY (case_id, judge_id)
);

-- Graph nodes: laws / provisions
CREATE TABLE IF NOT EXISTS laws (
    id        INTEGER PRIMARY KEY,
    provision TEXT NOT NULL,
    act       TEXT NOT NULL,
    UNIQUE (provision, act)
);

-- Graph edges: case <-> law
CREATE TABLE IF NOT EXISTS case_laws (
    case_id INTEGER NOT NULL REFERENCES cases(id),
    law_id  INTEGER NOT NULL REFERENCES laws(id),
    PRIMARY KEY (case_id, law_id)
);

-- Graph edges: case -> cited case (precedents used in judgment)
CREATE TABLE IF NOT EXISTS precedents (
    case_id        INTEGER NOT NULL REFERENCES cases(id),
    cited_citation TEXT    NOT NULL,
    cited_name     TEXT,
    PRIMARY KEY (case_id, cited_citation)
);

CREATE INDEX IF NOT EXISTS idx_cases_year ON cases(year);
CREATE INDEX IF NOT EXISTS idx_cases_reporter ON cases(reporter);
CREATE INDEX IF NOT EXISTS idx_cases_enriched ON cases(enriched);
"""

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
BULLET = '\u00b7'   # ·

def clean(s):
    return s.strip().replace('\u00e2\u20ac\u201c', '-').replace('\u00c2\u00b7', '·')

def fix_encoding(s):
    # The file was saved as latin-1 / cp1252 but read as utf-8 — fix mojibake
    try:
        return s.encode('latin-1').decode('utf-8')
    except Exception:
        return s

def parse_citation(raw):
    raw = raw.strip()
    year_m = re.search(r'\b(19\d\d|20\d\d)\b', raw)
    year = int(year_m.group(1)) if year_m else None

    # reporter: strip year from front, strip page from end
    reporter = re.sub(r'^\(?\s*(19\d\d|20\d\d)\s*\)?\.?\s*', '', raw)
    reporter = re.sub(r'\s*[\(\[]?\s*\d{1,4}[a-z]*\s*[\)\]]?\s*$', '', reporter,
                      flags=re.IGNORECASE)
    reporter = reporter.strip().rstrip('.,')

    page_m = re.search(r'(\d{1,4}[a-z]*)\s*[\)\]]?\s*$', raw, re.IGNORECASE)
    page = page_m.group(1) if page_m else ''

    return year, reporter, page

def split_parties(name):
    for sep in [' vs ', ' versus ', ' Versus ', ' VS ', ' Vs ']:
        if sep in name:
            parts = name.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return name.strip(), '[Respondent truncated]'

CITE_RE = re.compile(
    r'^[\(\[]?(K\.?L\.?R\.?\s+)?(19\d\d|20\d\d)|^(19\d\d|20\d\d)|^PLJ|^PLC|^\d{4}',
    re.IGNORECASE
)

STRAY_PREFIXES = ('and ', 'and Justice', 'and Ch.', 'and Nazar',
                  'and Rashid', 'and Muhammad Ayub', 'and Syed')

# ---------------------------------------------------------------------------
# Parse raw listing text
# ---------------------------------------------------------------------------
def parse_lines(text):
    # Try to fix mojibake (file saved with wrong encoding)
    try:
        fixed = text.encode('latin-1').decode('utf-8')
    except Exception:
        fixed = text

    lines = [l.strip() for l in fixed.splitlines()]
    lines = [l for l in lines if l]

    entries = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip header noise
        if (line.startswith('Federal Service Tribunal') or
                line.startswith('Judgments of the Federal Service Tribunal')):
            i += 1
            continue

        # Peek at next line for citation
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            if (CITE_RE.match(nxt) and
                    ('\u00b7 Federal Service Tribunal' in nxt or
                     'Federal Service Tribunal' in nxt)):
                case_name = line
                # Strip citation sentinel
                raw_cite = re.sub(r'\s*[\u00b7·]\s*Federal Service Tribunal.*', '', nxt).strip()

                primary = raw_cite.split(',')[0].strip()
                year, reporter, page = parse_citation(primary)
                petitioner, respondent = split_parties(case_name)

                notes_parts = []
                if any(case_name.startswith(p) for p in STRAY_PREFIXES):
                    notes_parts.append('stray-prefix')
                if respondent == '[Respondent truncated]':
                    notes_parts.append('no-vs-found')

                entries.append({
                    'case_name':  case_name,
                    'petitioner': petitioner,
                    'respondent': respondent,
                    'citation':   raw_cite,
                    'year':       year,
                    'reporter':   reporter,
                    'page':       page,
                    'notes':      '; '.join(notes_parts),
                })
                i += 2
                continue
        i += 1
    return entries

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"Reading {RAW_FILE} ...")
    with open(RAW_FILE, encoding='utf-8', errors='replace') as f:
        text = f.read()

    entries = parse_lines(text)
    print(f"Parsed {len(entries)} entries")

    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print("Removed old database")

    con = sqlite3.connect(DB_FILE)
    con.executescript(SCHEMA)

    rows = [(i + 1, e['case_name'], e['petitioner'], e['respondent'],
             e['citation'], e['year'], e['reporter'], e['page'],
             'Federal Service Tribunal', e['notes'])
            for i, e in enumerate(entries)]

    con.executemany(
        'INSERT INTO cases (id,case_name,petitioner,respondent,citation,'
        'year,reporter,page,court,notes) VALUES (?,?,?,?,?,?,?,?,?,?)',
        rows
    )
    con.commit()

    total = con.execute('SELECT COUNT(*) FROM cases').fetchone()[0]
    year_range = con.execute('SELECT MIN(year), MAX(year) FROM cases').fetchone()
    print(f"Database built: {total} cases, years {year_range[0]}–{year_range[1]}")
    print(f"Output: {DB_FILE}")

    con.close()

if __name__ == '__main__':
    main()
