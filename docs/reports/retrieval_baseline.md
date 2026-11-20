# Retrieval baseline (28 judgments)

**Date:** 2026-11-20 · **Corpus:** 28 enriched judgments, Constitution (27th Amendment), Service Tribunals Act 1973, Civil Servants Act 1973, E&D Rules 2020.

## Method

Leave-one-out (gold set E1): each legal question recorded for a judgment is used as a query, with that judgment hidden from retrieval. A retrieved statute unit is relevant if the hidden judgment applied it. Only units whose text is in the corpus count as gold, so judgments citing only rules we have not sourced yet are left out.

A **popularity control** ignores the query and ranks units by how many other judgments apply them. A method that uses the question has to beat it.

Reproduce:

```
python -m fstlegal.corpus.build
python -m fstlegal.eval.retrieval_eval --modes bm25 bm25+graph
python -m fstlegal.eval.retrieval_eval --modes bm25 bm25+graph --ignore-common 0.3
```

## Results

All gold units (73 queries, 22 judgments):

| Mode | R@1 | R@3 | R@5 | R@10 | nDCG@10 | MRR |
|---|---|---|---|---|---|---|
| Popularity (control) | 0.461 | 0.559 | 0.616 | 0.726 | 0.670 | 0.768 |
| BM25 | 0.083 | 0.125 | 0.169 | 0.226 | 0.159 | 0.182 |
| BM25 + graph | 0.254 | 0.394 | 0.517 | 0.666 | 0.492 | 0.512 |

Without units applied by more than 30% of judgments (drops STA s.4, the right-of-appeal section; 45 queries, 13 judgments):

| Mode | R@1 | R@3 | R@5 | R@10 | nDCG@10 | MRR |
|---|---|---|---|---|---|---|
| Popularity (control) | 0.000 | 0.196 | 0.307 | 0.496 | 0.300 | 0.285 |
| BM25 | 0.078 | 0.091 | 0.119 | 0.163 | 0.130 | 0.173 |
| BM25 + graph | 0.033 | 0.089 | 0.194 | 0.381 | 0.213 | 0.210 |

Raw numbers: `retrieval_all.json`, `retrieval_specific.json`.

## Reading

- Adding the graph to BM25 more than doubles recall@10 (0.226 → 0.666; 0.163 → 0.381 without s.4).
- BM25 alone is weak because questions and statute text use different words ("dismissed without a show-cause notice" vs the wording of the E&D Rules). This is the gap dense retrieval is meant to close.
- **The popularity control still wins at this size.** With 28 judgments, a few provisions (STA s.4, Constitution Art. 25) are applied in most cases, so always suggesting them scores well. This test cannot yet separate "uses the question" from "suggests what is common". It has to be re-run at full scale (about 2,000 judgments), where the distribution of provisions is wider, before any claim about graph retrieval is made.
- Only 48 of 112 law references point at text in the corpus, because the 1973 E&D Rules, Appeal Rules, APT Rules and Seniority Rules are not sourced yet. Adding them grows the gold set.

## Next

1. Dense and hybrid modes once the embedding model is served (Phase 3).
2. Popularity as a prior inside the fusion, compared against this control.
3. Re-run at full corpus size.
