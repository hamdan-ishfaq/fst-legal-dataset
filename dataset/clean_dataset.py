"""Build a clean dataset of fully enriched FST cases.

Keeps only cases whose judgment text and enrichment fields are present and
valid, normalises types and outcomes, and writes fst_cases_clean.csv. The
source file is left untouched. Rows that are dropped are counted by reason.

Usage: python dataset/clean_dataset.py [--src FILE] [--out FILE]
"""
import argparse
import json
import os
import re
from collections import Counter

import pandas as pd

from fstlegal.corpus.outcomes import normalize_outcome

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'fst_cases_v4.csv')
OUT = os.path.join(HERE, 'fst_cases_clean.csv')

REQUIRED = ['full_text', 'summary', 'outcome', 'bench_members',
            'questions_json', 'laws_json', 'keywords', 'precedents_json']
JSON_COLS = ['bench_members', 'questions_json', 'laws_json', 'precedents_json']

# Judgments that pakistancaselaw.com itself serves cut off before the ruling.
# Their laws/precedents are still usable; their outcome is not reliable.
TRUNCATED_SITE_IDS = {196802, 196007, 194790}



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


def valid_json(value):
    try:
        json.loads(value)
        return True
    except (TypeError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--src', default=SRC)
    parser.add_argument('--out', default=OUT)
    args = parser.parse_args()

    df = pd.read_csv(args.src, encoding='utf-8-sig')
    dropped = Counter()

    keep = df['enriched'] == 1
    dropped['not enriched'] = int((~keep).sum())
    for c in REQUIRED:
        missing = keep & (df[c].isna() | (df[c].astype(str).str.strip() == ''))
        dropped[f'missing {c}'] = int(missing.sum())
        keep &= ~missing
    for c in JSON_COLS:
        bad = keep & ~df[c].map(valid_json)
        dropped[f'invalid JSON in {c}'] = int(bad.sum())
        keep &= ~bad
    df = df.loc[keep].copy()

    for c in df.select_dtypes(include=['object', 'str']).columns:
        df[c] = df[c].where(df[c].isna(), df[c].astype(str).str.strip())
    df['full_text'] = df['full_text'].map(clean_text)
    df['summary'] = df['summary'].map(clean_text)

    for c in JSON_COLS:
        df[c] = df[c].map(lambda v: json.dumps(json.loads(v), ensure_ascii=False))

    df['outcome_raw'] = df['outcome']
    df['outcome'] = df['outcome'].map(normalize_outcome)
    unknown = df.loc[df['outcome'] == 'unknown', 'outcome_raw'].unique()

    df['decision_date'] = df['decision_date'].map(parse_date)
    df['year'] = df['year'].astype('Int64')
    df['site_id'] = df['site_id'].astype('Int64')
    df['text_truncated'] = df['site_id'].isin(TRUNCATED_SITE_IDS).astype(int)
    df['keywords'] = df['keywords'].map(
        lambda s: ', '.join(k.strip() for k in s.split(',') if k.strip()))

    df = df.drop(columns=['enriched', 'notes'])
    df = df.drop_duplicates(subset='citation').sort_values(['year', 'id'], ascending=[False, True])

    df.to_csv(args.out, index=False, encoding='utf-8-sig')
    print(f'Wrote {len(df)} cases -> {args.out}')
    for reason, n in dropped.items():
        if n:
            print(f'  dropped {n}: {reason}')
    print('  outcomes: ' + ', '.join(f'{k} {v}' for k, v in df['outcome'].value_counts().items()))
    if len(unknown):
        print(f'  outcome wording not recognised (labelled unknown): {list(unknown)[:10]}')


if __name__ == '__main__':
    main()
