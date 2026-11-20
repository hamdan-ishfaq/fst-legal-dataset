"""Build a clean dataset of fully enriched FST cases from fst_cases_v4.csv.

Keeps only cases whose judgment text and LLM-derived fields are present,
normalises types and outcomes, and writes fst_cases_clean.csv. The source
file is left untouched.
"""
import json
import os
import re

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'fst_cases_v4.csv')
OUT = os.path.join(HERE, 'fst_cases_clean.csv')

REQUIRED = ['full_text', 'summary', 'outcome', 'bench_members',
            'questions_json', 'laws_json', 'keywords', 'precedents_json']
JSON_COLS = ['bench_members', 'questions_json', 'laws_json', 'precedents_json']

# Judgments that pakistancaselaw.com itself serves cut off before the ruling.
# Their laws/precedents are still usable; their outcome is not reliable.
TRUNCATED_SITE_IDS = {196802, 196007, 194790}

OUTCOME_MAP = {
    'allowed': 'allowed',
    'appeal accepted.': 'allowed',
    'dismissed': 'dismissed',
    'appeal disposed of.': 'disposed_of',
    'order accordingly.': 'disposed_of',
}


def clean_text(s):
    s = s.replace('\r\n', '\n').replace('\xa0', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n\s*\n+', '\n\n', s)
    return s.strip()


def parse_date(s):
    if pd.isna(s):
        return None
    s = re.sub(r'(\d)(st|nd|rd|th)', r'\1', str(s)).replace(',', '')
    d = pd.to_datetime(s, format='%d %B %Y', errors='coerce')
    return None if pd.isna(d) else d.date().isoformat()


def main():
    df = pd.read_csv(SRC, encoding='utf-8-sig')

    keep = df['enriched'] == 1
    for c in REQUIRED:
        keep &= df[c].notna() & (df[c].astype(str).str.strip() != '')
    df = df.loc[keep].copy()

    for c in df.select_dtypes(include=['object', 'str']).columns:
        df[c] = df[c].where(df[c].isna(), df[c].astype(str).str.strip())
    df['full_text'] = df['full_text'].map(clean_text)
    df['summary'] = df['summary'].map(clean_text)

    for c in JSON_COLS:
        df[c] = df[c].map(lambda v: json.dumps(json.loads(v), ensure_ascii=False))

    df['outcome_raw'] = df['outcome']
    df['outcome'] = df['outcome'].str.lower().map(OUTCOME_MAP)
    unmapped = df.loc[df['outcome'].isna(), 'outcome_raw'].unique()
    if len(unmapped):
        raise ValueError(f'Unmapped outcomes: {list(unmapped)}')

    df['decision_date'] = df['decision_date'].map(parse_date)
    df['year'] = df['year'].astype('Int64')
    df['site_id'] = df['site_id'].astype('Int64')
    df['text_truncated'] = df['site_id'].isin(TRUNCATED_SITE_IDS).astype(int)
    df['keywords'] = df['keywords'].map(
        lambda s: ', '.join(k.strip() for k in s.split(',') if k.strip()))

    df = df.drop(columns=['enriched', 'notes'])
    df = df.drop_duplicates(subset='citation').sort_values(['year', 'id'], ascending=[False, True])

    df.to_csv(OUT, index=False, encoding='utf-8-sig')
    print(f'Wrote {len(df)} cases -> {OUT}')


if __name__ == '__main__':
    main()
