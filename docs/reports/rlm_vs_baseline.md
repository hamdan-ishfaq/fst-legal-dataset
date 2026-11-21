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

## Next

1. Same two runs with the RLM fine-tune (community Q4_K_M, `rlm_community`); then one table: baseline vs RLM base vs RLM fine-tuned, short and long.
2. Write the final brief with one schema-constrained call over the RLM's notes; feed graph-expanded provisions into the RLM's context.
