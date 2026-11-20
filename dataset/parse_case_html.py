"""
Parse one or many full case-page HTML dumps from pakistancaselaw.com.
Feed: new.txt (or any file with one or more case pages concatenated).

Extracts from each page:
  - site_id, citation, court, bench, parties, appeal_number, decision_date
  - outcome (from "Result: Appeals allowed" / "dismissed" etc.)
  - summary, questions, laws, keywords/tags
  - full judgment text (plain, no HTML)
  - cited precedents (case links in body text)
  - authoring judge

Matches to fst.db by site_id, then by citation, and updates that row.

Usage:
    python parse_case_html.py              # processes new.txt
    python parse_case_html.py path/to/file  # processes another file
"""

import os, re, sqlite3, json, sys
from html import unescape

HERE     = os.path.dirname(os.path.abspath(__file__))
DB_FILE  = os.path.join(HERE, 'fst.db')
IN_FILE  = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'new.txt')
BASE_URL = 'https://pakistancaselaw.com'

# ---------------------------------------------------------------------------
# Split file into individual case pages (each starts with var CID=<number>)
# ---------------------------------------------------------------------------
def split_pages(html):
    """
    Split concatenated case-page HTML into individual pages.
    Each page is demarcated by <article> ... </article> containing .phead,
    plus the subsequent <script> block that holds var CID=.
    Strategy: find each <article>, grab everything from the preceding
    <div class="crumbs"> through to the next <div class="crumbs"> (or EOF).
    That window always contains both the content and the CID script.
    """
    # Split on the crumbs div that leads each case article
    chunks = re.split(r'(?=<div class="crumbs">)', html)
    pages = []
    for chunk in chunks:
        if re.search(r'var CID=\d', chunk) or re.search(r'<div class="p-cite">', chunk):
            pages.append(chunk)
    if not pages:
        # Fallback: treat the whole file as one page
        pages = [html]
    return pages

# ---------------------------------------------------------------------------
# Strip HTML tags from a string
# ---------------------------------------------------------------------------
TAG_RE = re.compile(r'<[^>]+>')

def strip_tags(s):
    s = TAG_RE.sub(' ', s)
    s = unescape(s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def inner_text(html_frag):
    return strip_tags(html_frag)

# ---------------------------------------------------------------------------
# Parse a single case page
# ---------------------------------------------------------------------------
def parse_page(html):
    data = {}

    # --- site_id and URL from JS variable ---
    m = re.search(r'var CID=(\d+)', html)
    if not m:
        return None
    data['site_id'] = int(m.group(1))

    m = re.search(r"var URL_=['\"]([^'\"]+)['\"]", html)
    data['source_url'] = m.group(1) if m else BASE_URL + f"/case/{data['site_id']}/"

    # --- Citation ---
    m = re.search(r'<div class="p-cite">([^<]+)</div>', html)
    data['citation'] = unescape(m.group(1).strip()) if m else ''

    # --- Court ---
    m = re.search(r'<div class="p-court">\[?([^\]<]+)\]?</div>', html)
    data['court'] = unescape(m.group(1).strip()) if m else 'Federal Service Tribunal'

    # --- Bench members ---
    m = re.search(r'<div class="p-bench">Present:\s*(.*?)</div>', html, re.DOTALL)
    bench_raw = strip_tags(m.group(1)) if m else ''
    bench_members = [n.strip() for n in re.split(r',\s*', bench_raw) if n.strip()]
    data['bench_members'] = bench_members

    # --- Parties ---
    m = re.search(r'<h1 class="p-parties"><span>(.*?)</span>\s*<span class="p-vs">.*?</span>\s*<span>(.*?)</span></h1>',
                  html, re.DOTALL)
    if m:
        data['petitioner']  = unescape(m.group(1).strip())
        data['respondent']  = unescape(m.group(2).strip())
    else:
        data['petitioner']  = ''
        data['respondent']  = ''

    # --- Appeal number and decision date ---
    m = re.search(r'<div class="p-caseno">(.*?)</div>', html, re.DOTALL)
    caseno_raw = strip_tags(m.group(1)) if m else ''
    data['appeal_number'] = caseno_raw

    # Extract decision date from caseno string
    dm = re.search(r'decided on (.+?)\.?\s*$', caseno_raw, re.I)
    data['decision_date'] = dm.group(1).strip() if dm else ''

    # --- Outcome (from p-more div) ---
    m = re.search(r'<div class="p-more">(.*?)</div>', html, re.DOTALL)
    more_raw = strip_tags(m.group(1)) if m else ''
    outcome = ''
    om = re.search(r'Result:\s*(.+)', more_raw, re.I)
    if om:
        result_text = om.group(1).strip().lower()
        if 'allow' in result_text:
            outcome = 'allowed'
        elif 'dismiss' in result_text:
            outcome = 'dismissed'
        elif 'partly' in result_text or 'partial' in result_text:
            outcome = 'partly allowed'
        else:
            outcome = om.group(1).strip()
    data['outcome'] = outcome

    # --- Summary ---
    m = re.search(r'<section class="headnote">.*?<p>(.*?)</p>', html, re.DOTALL)
    data['summary'] = strip_tags(m.group(1)) if m else ''

    # --- Questions ---
    m = re.search(r'<div class="hn-qs">.*?<ul>(.*?)</ul>', html, re.DOTALL)
    questions = []
    if m:
        for li in re.findall(r'<li>(.*?)</li>', m.group(1), re.DOTALL):
            questions.append(strip_tags(li))
    data['questions'] = questions

    # --- Laws referred ---
    m = re.search(r'<div class="hn-laws">.*?<ul>(.*?)</ul>', html, re.DOTALL)
    laws = []
    if m:
        for li in re.findall(r'<li>(.*?)</li>', m.group(1), re.DOTALL):
            text = strip_tags(li)
            # Format: "Section 4, Federal Service Tribunals Act, 1973"
            # Split at first comma
            parts = text.split(',', 1)
            if len(parts) == 2:
                laws.append({'provision': parts[0].strip(), 'act': parts[1].strip()})
            else:
                laws.append({'provision': text, 'act': ''})
    data['laws'] = laws

    # --- Tags / keywords ---
    keywords = re.findall(r'<span class="hn-tag">([^<]+)</span>', html)
    data['keywords'] = [unescape(k) for k in keywords]

    # --- Cited precedents (links inside judgment body) ---
    # <a class="cl" href="/case/104436/...">2005 SCMR 890</a>
    m_body = re.search(r'<section class="body"[^>]*>(.*?)</section>', html, re.DOTALL)
    precedents = []
    if m_body:
        body_html = m_body.group(1)
        for cm in re.finditer(r'<a class="cl" href="/case/(\d+)/([^"]+)">([^<]+)</a>', body_html):
            cited_sid   = int(cm.group(1))
            cited_cite  = unescape(cm.group(3).strip())
            precedents.append({'citation': cited_cite, 'site_id': cited_sid, 'name': ''})
    data['precedents'] = precedents

    # --- Full text (plain) ---
    if m_body:
        data['full_text'] = strip_tags(m_body.group(1))
    else:
        data['full_text'] = ''

    # --- Authoring judge ---
    m = re.search(r'Authored by <a[^>]+>([^<]+)</a>', html)
    data['authored_by'] = unescape(m.group(1).strip()) if m else ''

    return data

# ---------------------------------------------------------------------------
# Normalize laws list: remove duplicate provision+act pairs
# ---------------------------------------------------------------------------
def dedup_laws(laws):
    seen = set()
    out = []
    for l in laws:
        key = (l['provision'], l['act'])
        if key not in seen:
            seen.add(key)
            out.append(l)
    return out

# ---------------------------------------------------------------------------
# Write to DB
# ---------------------------------------------------------------------------
def _get_or_create_judge(con, name):
    name = name.strip()
    if not name:
        return None
    con.execute('INSERT OR IGNORE INTO judges(name) VALUES (?)', (name,))
    return con.execute('SELECT id FROM judges WHERE name=?', (name,)).fetchone()[0]

def _get_or_create_law(con, provision, act):
    provision, act = provision.strip(), act.strip()
    con.execute('INSERT OR IGNORE INTO laws(provision, act) VALUES (?,?)', (provision, act))
    return con.execute('SELECT id FROM laws WHERE provision=? AND act=?', (provision, act)).fetchone()[0]

def save_to_db(con, data):
    sid = data['site_id']

    # Find case in DB
    row = con.execute('SELECT id FROM cases WHERE site_id=?', (sid,)).fetchone()
    if not row:
        # Try by citation
        row = con.execute('SELECT id FROM cases WHERE citation=?', (data['citation'],)).fetchone()
    if not row:
        print(f"  NOT FOUND in DB: site_id={sid} citation={data['citation']!r}")
        return False
    cid = row[0]

    laws = dedup_laws(data['laws'])

    con.execute("""
        UPDATE cases SET
            appeal_number  = ?,
            decision_date  = ?,
            bench_members  = ?,
            outcome        = ?,
            summary        = ?,
            questions_json = ?,
            laws_json      = ?,
            keywords       = ?,
            precedents_json = ?,
            full_text      = ?,
            enriched       = 1,
            updated_at     = datetime('now')
        WHERE id = ?
    """, (
        data['appeal_number'],
        data['decision_date'],
        json.dumps(data['bench_members'], ensure_ascii=False),
        data['outcome'],
        data['summary'],
        json.dumps(data['questions'],     ensure_ascii=False),
        json.dumps(laws,                  ensure_ascii=False),
        ', '.join(data['keywords']),
        json.dumps(data['precedents'],    ensure_ascii=False),
        data['full_text'],
        cid,
    ))

    # Judges
    for name in data['bench_members']:
        jid = _get_or_create_judge(con, name)
        if jid:
            con.execute('INSERT OR IGNORE INTO case_judges(case_id, judge_id, role) VALUES (?,?,?)',
                        (cid, jid, 'member'))

    # Laws
    for l in laws:
        lid = _get_or_create_law(con, l['provision'], l['act'])
        con.execute('INSERT OR IGNORE INTO case_laws(case_id, law_id) VALUES (?,?)', (cid, lid))

    # Precedents
    for p in data['precedents']:
        con.execute('INSERT OR REPLACE INTO precedents(case_id, cited_citation, cited_name) VALUES (?,?,?)',
                    (cid, p['citation'], p.get('name', '')))

    return True

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    with open(IN_FILE, encoding='utf-8', errors='replace') as f:
        html = f.read()

    pages = split_pages(html)
    print(f"Found {len(pages)} case page(s) in {IN_FILE}")

    con = sqlite3.connect(DB_FILE)
    con.execute('PRAGMA foreign_keys=ON')

    saved = 0
    for i, page in enumerate(pages, 1):
        data = parse_page(page)
        if not data:
            print(f"  Page {i}: could not parse")
            continue
        cite = data.get('citation', '')
        sid  = data.get('site_id', '')
        ok = save_to_db(con, data)
        if ok:
            saved += 1
            print(f"  [{i}] Saved: site_id={sid}  {cite}  outcome={data['outcome']!r}"
                  f"  q={len(data['questions'])}  laws={len(data['laws'])}"
                  f"  prec={len(data['precedents'])}")
        else:
            print(f"  [{i}] Skipped (not in FST DB): site_id={sid}  {cite}")

    con.commit()
    enriched = con.execute('SELECT COUNT(*) FROM cases WHERE enriched=1').fetchone()[0]
    print(f"\nDone. {saved} case(s) enriched this run. Total enriched: {enriched}/2278")
    con.close()

if __name__ == '__main__':
    main()
