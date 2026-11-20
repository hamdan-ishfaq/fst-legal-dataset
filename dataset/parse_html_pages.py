"""
Parse HTML listing pages from pakistancaselaw.com/browse/court/federal-service-tribunal
and populate site_id, source_url, case_name_full in fst.db.

Feed it any number of saved HTML files:
    python parse_html_pages.py body.txt page2.html page3.html ...

Or point it at a directory of saved pages:
    python parse_html_pages.py C:/path/to/html_pages/
"""
import re
import sqlite3
import sys
import os
from html import unescape

HERE    = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(HERE, 'fst.db')
BASE_URL = 'https://pakistancaselaw.com'

# Pattern: <a href="/case/SITEID/slug">Case Name</a>
#          <span class="sub">CITATION · Federal Service Tribunal</span>
ENTRY_RE = re.compile(
    r'<a href="(/case/(\d+)/[^"]+)">([^<]+)</a>'
    r'[^<]*(?:<[^/][^>]*>)*[^<]*'
    r'<span class="sub">([^<]+?)\s*·\s*Federal Service Tribunal</span>',
    re.DOTALL
)

def parse_html(html):
    """Return list of (site_id, source_path, full_name, citation)."""
    entries = []
    for m in ENTRY_RE.finditer(html):
        path      = m.group(1)
        site_id   = int(m.group(2))
        full_name = unescape(m.group(3).strip())
        citation  = unescape(m.group(4).strip())
        entries.append((site_id, path, full_name, citation))
    return entries

def match_and_update(con, entries):
    updated = 0
    inserted_new = 0
    for site_id, path, full_name, citation in entries:
        # Try to find by citation (strip whitespace variants)
        # Normalize citation for matching: compress spaces
        cite_norm = re.sub(r'\s+', ' ', citation).strip()

        row = con.execute(
            'SELECT id FROM cases WHERE trim(citation)=? OR site_id=?',
            (cite_norm, site_id)
        ).fetchone()

        # Fallback: match by year + page extracted from citation
        if not row:
            yr_m  = re.search(r'\b(19\d\d|20\d\d)\b', cite_norm)
            pg_m  = re.search(r'(\d{1,4}[a-z]*)\s*[\)\]]?\s*$', cite_norm, re.I)
            if yr_m and pg_m:
                yr, pg = yr_m.group(1), pg_m.group(1)
                row = con.execute(
                    'SELECT id FROM cases WHERE year=? AND page=? AND site_id IS NULL',
                    (int(yr), pg)
                ).fetchone()

        if row:
            cid = row[0]
            con.execute(
                'UPDATE cases SET site_id=?, source_url=?, case_name_full=? WHERE id=?',
                (site_id, BASE_URL + path, full_name, cid)
            )
            updated += 1
        else:
            # Not in DB yet — insert as new entry (unusual but possible)
            print(f"  NOT MATCHED (site_id={site_id}): {citation[:60]}")
    return updated, inserted_new


def process_file(path, con):
    with open(path, encoding='utf-8', errors='replace') as f:
        html = f.read()
    entries = parse_html(html)
    if not entries:
        print(f"  No entries found in {path}")
        return
    updated, new = match_and_update(con, entries)
    print(f"  {path}: {len(entries)} entries → {updated} updated")


def main():
    args = sys.argv[1:]
    if not args:
        # Default: use body.txt in the FYP folder
        args = [os.path.join(HERE, '..', 'body.txt')]

    con = sqlite3.connect(DB_FILE)

    for arg in args:
        if os.path.isdir(arg):
            for fname in sorted(os.listdir(arg)):
                if fname.endswith(('.html', '.txt', '.htm')):
                    process_file(os.path.join(arg, fname), con)
        else:
            process_file(arg, con)

    con.commit()

    total_with_url = con.execute('SELECT COUNT(*) FROM cases WHERE site_id IS NOT NULL').fetchone()[0]
    total = con.execute('SELECT COUNT(*) FROM cases').fetchone()[0]
    print(f"\nDone. {total_with_url}/{total} cases have a site_id and URL")
    con.close()


if __name__ == '__main__':
    main()
