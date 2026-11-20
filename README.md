# FST Legal Dataset

Structured dataset of Federal Service Tribunal (Pakistan) judgments from pakistancaselaw.com, built for GraphRAG work.

- `dataset/fst.db`: SQLite database, 2278 cases (1975–2026)
- `dataset/fst_cases.csv`: full CSV export of the `cases` table
- `dataset/fst_cases_clean.csv`: fully enriched cases only, normalized (built by `dataset/clean_dataset.py`)
- `docs/`: implementation plan, architecture decisions and literature review

## Layout

| File | Purpose |
|---|---|
| `New Text Document.txt` | Raw FST listing text (all 23 pages) |
| `body.txt` | HTML of the listing pages (site IDs and URLs) |
| `new.txt` | Concatenated HTML of individual judgment pages |
| `dataset/build_db.py` | Builds `fst.db` from the listing text |
| `dataset/parse_html_pages.py` | Adds `site_id`, `source_url`, `case_name_full` from `body.txt` |
| `dataset/parse_case_html.py` | Enriches cases from judgment page HTML |
| `dataset/enrich_case.py` | `enrich()` helper for adding case details manually |
| `dataset/export_csv.py` | Writes `dataset/fst_cases.csv` from the database |

## Adding judgments

1. Open a case page on pakistancaselaw.com, copy the page HTML, and append it to a text file. Any number of pages can go in one file.
2. Run the parser on that file:
   ```
   python dataset/parse_case_html.py new.txt
   ```
3. Regenerate the CSV:
   ```
   python dataset/export_csv.py
   ```

Each parsed page fills `summary`, `questions_json`, `laws_json`, `keywords`, `precedents_json`, `bench_members`, `outcome`, `decision_date`, `appeal_number` and `full_text`, plus the `judges`, `case_judges`, `laws`, `case_laws` and `precedents` tables. Re-running the same file is safe; existing cases are overwritten with the same data.

## Working in parallel

`fst.db` is binary and git can't merge it. Keep scraped pages in your own file (e.g. `scraped/<name>_batch1.txt`), commit those text files, and rebuild the database from them, rather than both committing changes to `fst.db`.

## Schema

- `cases`: one row per citation (a case reported in two reporters appears twice with the same `site_id`)
- `judges`, `case_judges`: bench members
- `laws`, `case_laws`: statutory provisions referred
- `precedents`: citations referred to in the judgment body
