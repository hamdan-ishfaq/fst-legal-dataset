# Baseline vs RLM (28 judgments, one laptop)

**Date:** 2026-11-21 · **Hardware:** RTX 4050 Laptop (6 GB), 16 GB RAM · **Server:** llama.cpp b12588, Q4_K_M, all layers on the GPU

Each judgment's first legal question is answered with that judgment hidden from retrieval (leave-one-out). Gold provisions are those the hidden judgment applied. Same corpus, same retrieval, same scoring for every column.

Reproduce:

```
python scripts/serve.py chat [rlm_community]
python -m fstlegal.eval.baseline_check --out docs/reports/baseline_verification.json
python -m fstlegal.eval.baseline_check --pipeline rlm --out docs/reports/rlm_verification.json
```

## Results

| Metric | Baseline, Qwen3-8B | RLM, Qwen3-8B |
|---|---|---|
| Runs with a brief | 28 / 28 | 27 / 28 |
| Citation existence rate (kept claims) | 1.00 | 1.00 |
| Mean claims kept per brief | 17.5 | 5.0 |
| Claims removed for an invalid source | 14% | 32% |
| Gold provision recall | **0.269** | 0.098 |
| Mean time per brief | **42 s** | 176 s |
| Mean tokens per brief | 5,306 | 25,552 |
| Mean root turns / sub-calls | 1 / 0 | 6.1 / 0.8 |

Per-run numbers: `baseline_verification.json`, `rlm_verification.json`.

## Reading

- On the base model the RLM loses on every measure. This is what the RLM paper reports for models not trained on the scaffold, and is why the fine-tuned RLM-Qwen3-8B is the planned root model (D-002, D-007).
- The RLM barely delegates (0.8 sub-calls per run): base Qwen3-8B reads and searches itself instead of handing judgments to sub-calls, so the queue has little to distribute.
- Most removed claims cite provisions the model saw mentioned inside a judgment's text but never retrieved itself; the check correctly removes them, which also lowers gold recall.
- Most of the RLM's time is the root model's thinking before each turn (about 32 tokens/s on this GPU).
- These questions come with no case papers, so the baseline's single prompt already holds everything relevant. The RLM's claimed advantage (H1) is on material too long for one prompt, which the next section tests.

## Long case files (14 judgments)

Each question comes with a case file: the hidden judgment's own text up to its order (15k–48k characters, mean 25.6k). The baseline can fit only the first 9,000 characters (`PAPER_CHARS`); the RLM gets the whole file in `context`.

```
python -m fstlegal.eval.baseline_check --long --out docs/reports/baseline_long.json
python -m fstlegal.eval.baseline_check --long --pipeline rlm --out docs/reports/rlm_long.json
```

| Metric | Baseline, Qwen3-8B | RLM, Qwen3-8B |
|---|---|---|
| Runs with a brief | 13 / 14 (one answer cut off at the context limit) | 14 / 14 |
| Mean claims kept per brief | 14.0 | 6.7 |
| Claims removed for an invalid source | 21.6% | 22.3% |
| Gold provision recall | **0.171** | 0.106 |
| Mean time per brief | **47 s** | 150 s |
| Mean tokens per brief | 7,534 | 23,936 |
| Mean root turns / sub-calls | 1 / 0 | 6.1 / 0 |

The RLM's citation existence rate in `rlm_long.json` reads 0.93 because the checker then counted citations to the case file (`paper:case_file`) as missing; this was fixed after the run and all its cited ids do exist.

- With long input the RLM's removal rate falls to the baseline's level and it always produces a brief; the baseline once ran out of window before closing its answer.
- The base model still never delegates (0 sub-calls): it reads the case file itself. Delegation is what the fine-tune was trained to do, so the fine-tuned run is the real test of H1.

## Against the LLM alone, and with named provisions (2026-11-23)

`--pipeline closed` is the same Qwen3-8B with no retrieval, citing from memory; each citation is resolved against the corpus by name and scored like the baseline's (`closed_book_*.json`). After that run, the baseline was changed to put the provisions the case papers name first among its statute sources (`named_units`), and the long run was repeated (`baseline_long.json` now holds the new run).

| Metric | LLM alone | Baseline, before | Baseline, named provisions | RLM (before the change) |
|---|---|---|---|---|
| **Short questions:** gold provision recall | 0.075 | **0.269** | 0.269 (no case papers, unchanged) | 0.098 |
| **Short questions:** claims kept per brief | 0.8 | **17.5** | 17.5 | 5.0 |
| **Long case files:** gold provision recall | 0.366 | 0.171 | **0.574** | 0.106 |
| **Long case files:** claims kept per brief | 4.1 | 14.0 | **16.5** | 6.7 |
| **Long case files:** claims removed | 76% | 21.6% | **17.2%** | 22.3% |
| **Long case files:** invalid citations per brief | 11.1 | – | 0.4 | – |
| **Long case files:** time per brief | 50 s | 47 s | 47 s | 150 s |

- Without retrieval the model cites rules and cases that do not exist (e.g. a "Pakistan Administrative Service (Disciplinary Proceedings) Rules, 1973"), about 11 per brief; three quarters of its claims are removed. The system answers with checked citations.
- On long files the LLM alone first scored higher than the baseline: the case file names its provisions and the model copied the names, while the baseline could cite only what retrieval found from the question. Reading the named provisions as sources fixes this: the gold provisions among the sources go from 12 to 30 of 47, and recall from 0.171 to 0.574.
- Caveat: these case files are the judgments' own reasoning, which names provisions more consistently than a petition would; on real case papers the gain should be smaller.
- The RLM long run predates the change; the RLM now gets the named provisions in its context too, but has not been re-run.

## Next

1. Re-run the RLM long set with named provisions (about 35 minutes), and the same two runs with the RLM fine-tune (community Q4_K_M, `rlm_community`); then one table: baseline vs RLM base vs RLM fine-tuned, short and long.
2. Write the final brief with one schema-constrained call over the RLM's notes; feed graph-expanded provisions into the RLM's context.
