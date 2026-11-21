# Baseline verification (live model, 28 judgments)

**Date:** 2026-11-21 · **Model:** Qwen3-8B Q4_K_M, llama.cpp b12588 · **Hardware:** RTX 4050 Laptop (6 GB), 16 GB RAM

## Setup

All 36 layers on the GPU, 8k context, q8_0 KV cache, flash attention, weights loaded without a memory map (`config/runtime.toml`). This uses about 5.4 GB of VRAM and under 1 GB of system RAM. Generation runs at about 32 tokens/s and prompt processing at about 1,500 tokens/s.

For each judgment, its first legal question is answered by the baseline pipeline (retrieve 6 statute units and 4 judgments, one model call, citation check) with that judgment hidden from retrieval.

Reproduce:

```
python scripts/serve.py chat
python -m fstlegal.eval.baseline_check --out docs/reports/baseline_verification.json
```

## Results

| Metric | Value |
|---|---|
| Runs | 28 |
| Citation existence rate (kept claims citing a real source) | 1.00 |
| Mean claims kept per brief | 17.5 |
| Share of claims removed for citing no valid source | 14.2% |
| Gold provision recall (provisions the hidden judgment applied that the brief cites) | 0.269 |
| Mean time per brief | 42 s |
| Mean completion tokens | 1,257 |

Per-run numbers: `baseline_verification.json`.

## Reading

- No kept claim cites a source that was not given; the check removes about one claim in seven, so it is doing real work.
- Gold provision recall (0.27) is bounded by retrieval: the brief can only cite what the retriever supplies (the brief gets 6 units from BM25 + graph, whose R@5 is 0.35). This is the figure the RLM pipeline has to improve on (H1).
- 42 s per brief on one laptop is the single-node reference point for the latency comparison (H2).
