import os, sqlite3, csv

HERE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(HERE, 'fst.db')
OUT  = os.path.join(HERE, 'fst_cases.csv')

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = con.execute("""
    SELECT
        id, year, reporter, page, citation,
        case_name_full, case_name,
        petitioner, respondent,
        court, appeal_number, decision_date,
        bench_members, outcome,
        summary, questions_json, laws_json,
        keywords, precedents_json,
        full_text,
        notes, site_id, source_url, enriched
    FROM cases
    ORDER BY year DESC, id ASC
""").fetchall()

fields = list(rows[0].keys())
with open(OUT, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows([dict(r) for r in rows])

print(f"Exported {len(rows)} rows -> {OUT}")
con.close()
