# Retrieval baseline (28 judgments)

**Date:** 2026-11-21 · **Embedding:** Qwen3-Embedding-0.6B Q8_0 · **Corpus hash:** `e46d9481ea95`
**Corpus:** 28 enriched judgments; Constitution (27th Amendment); Service Tribunals Act 1973; Civil Servants Act 1973; E&D Rules 1973 and 2020; from ESTACODE 2021 the APT Rules 1973, Seniority Rules 1993, Appeal Rules 1977 and Service Tribunals (Procedure) Rules 1974.

## Method

Leave-one-out (gold set E1): each legal question recorded for a judgment is used as a query, with that judgment hidden from retrieval. A retrieved statute unit is relevant if the hidden judgment applied it. Only units whose text is in the corpus count as gold, so judgments citing only unsourced law are left out.

A **popularity control** ignores the query and ranks units by how many other judgments apply them. A method that uses the question has to beat it.

Reproduce:

```
python -m fstlegal.corpus.build
python scripts/serve.py embedding
MODES="bm25 dense hybrid hybrid+graph bm25+graph"
python -m fstlegal.eval.retrieval_eval --modes $MODES --embed-url http://127.0.0.1:8081
python -m fstlegal.eval.retrieval_eval --modes $MODES --embed-url http://127.0.0.1:8081 --ignore-common 0.3
```

## Results

All gold units (76 queries, 23 judgments):

| Mode | R@1 | R@3 | R@5 | R@10 | nDCG@10 | MRR |
|---|---|---|---|---|---|---|
| Popularity (control) | 0.342 | 0.421 | 0.425 | 0.504 | 0.524 | 0.735 |
| BM25 | 0.067 | 0.113 | 0.142 | 0.216 | 0.153 | 0.195 |
| Dense | 0.083 | 0.153 | 0.166 | 0.191 | 0.163 | 0.200 |
| Hybrid (BM25 + dense) | 0.080 | 0.129 | 0.176 | 0.245 | 0.179 | 0.219 |
| Hybrid + graph | 0.136 | 0.219 | 0.328 | 0.376 | 0.290 | 0.334 |
| BM25 + graph | 0.161 | 0.268 | 0.353 | **0.533** | 0.383 | 0.429 |

Without units applied by more than 30% of judgments (drops STA s.4, the right-of-appeal section; 61 queries, 18 judgments):

| Mode | R@1 | R@3 | R@5 | R@10 | nDCG@10 | MRR |
|---|---|---|---|---|---|---|
| Popularity (control) | 0.000 | 0.123 | 0.127 | 0.252 | 0.171 | 0.220 |
| BM25 | 0.057 | 0.122 | 0.151 | 0.180 | 0.139 | 0.176 |
| Dense | 0.056 | 0.148 | 0.167 | 0.181 | 0.146 | 0.167 |
| Hybrid (BM25 + dense) | 0.072 | 0.116 | 0.161 | 0.248 | 0.171 | 0.195 |
| Hybrid + graph | 0.088 | 0.156 | 0.269 | 0.278 | 0.218 | 0.226 |
| BM25 + graph | 0.080 | 0.137 | 0.203 | **0.290** | 0.210 | 0.231 |

Raw numbers: `retrieval_all.json`, `retrieval_specific.json`.

## Reading

- **BM25 + graph now passes the popularity control on recall@10** (0.533 vs 0.504; 0.290 vs 0.252 without s.4). In the previous run, with only 48 of 112 law references pointing at text, the control was ahead (0.726 vs 0.666). Adding the ESTACODE rules widened the set of provisions the judgments apply (67 of 112 now have text), so suggesting the common ones no longer suffices. The control still ranks its few hits higher (MRR 0.735), so the graph's gain is in coverage, not in first place.
- The graph more than doubles keyword recall in both settings (0.216 → 0.533; 0.180 → 0.290).
- Dense retrieval alone is no better than BM25 here; fusing the two is best among text-only modes. Hybrid + graph is below BM25 + graph: dense hits are spread over more judgments, so the provisions the graph collects from them are less focused.
- 23 judgments is far too few for firm conclusions. The test is re-run at full size (about 2,000 judgments) before any claim in the thesis.

## Next

1. Popularity as a prior inside the fusion, compared against this control.
2. Re-run at full corpus size.
