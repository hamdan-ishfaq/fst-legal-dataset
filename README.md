# FST Case-Preparation Assistant

An on-premise legal research tool for Federal Service Tribunal (Pakistan) practice. It links FST judgments, the Constitution and the service statutes into a knowledge graph, and answers a lawyer's questions with a brief in which every statement cites a judgment or statute section. Complex questions run on a recursive language model whose sub-calls can be spread across laptops on the office network. Everything runs offline.

## Documents

| Document | Contents |
|---|---|
| [docs/SRS.md](docs/SRS.md) | Requirements (FR/NFR) and use cases |
| [docs/LITERATURE_REVIEW.md](docs/LITERATURE_REVIEW.md) | Related work and the gap this project addresses |
| [docs/SDS.md](docs/SDS.md) | Architecture, data design, components, interfaces |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | Test cases, evaluation and traceability matrix |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Phase-by-phase build plan |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decisions and the options compared |
| [docs/reports/](docs/reports/) | Corpus quality and evaluation results |

## Setup

```
pip install -e ".[dev]"
```

## Pipeline

```
# 1. clean the scraped dataset (keeps fully enriched judgments, reports what is dropped)
python dataset/clean_dataset.py --src dataset/fst_cases_v4.csv

# 2. build the corpus: judgments, Constitution, statutes, chunks, graph links, FTS index
python -m fstlegal.corpus.build          # writes data/build/corpus.db and quality_report.md

# 3. evaluate retrieval (leave-one-out)
python -m fstlegal.eval.retrieval_eval --modes bm25 bm25+graph

# 4. answer a question with the baseline pipeline (needs llama-server on :8080)
python -m fstlegal.pipeline.baseline "Can a civil servant be dismissed without a regular inquiry?"
```

Model runtime: `python scripts/fetch_runtime.py` downloads the pinned llama.cpp build and model files listed in `config/runtime.toml` into `runtime/`.

## Tests

```
ruff check .
pytest -m "not model"      # unit and data tests, as run in CI
pytest -m model            # integration tests against a running llama-server
```

## Layout

| Path | Purpose |
|---|---|
| `dataset/` | Scraping and enrichment scripts, `fst.db`, the clean dataset |
| `data/sources/` | Official statute and Constitution texts, with editions in its README |
| `fstlegal/corpus/` | Parsing, normalization, chunking, corpus build |
| `fstlegal/retrieval/` | BM25, embeddings, knowledge graph, rank fusion |
| `fstlegal/llm/` | Client for the local model server |
| `fstlegal/pipeline/` | Baseline pipeline (RLM pipeline to follow) |
| `fstlegal/eval/` | Evaluation sets and metrics |
| `tests/` | Unit and data tests |

## Adding judgments

1. Copy the HTML of case pages from pakistancaselaw.com into a text file.
2. `python dataset/parse_case_html.py <file>` to parse it into `dataset/fst.db`.
3. `python dataset/export_csv.py`, then run the pipeline above.

`fst.db` is binary and git can't merge it. Keep scraped pages in your own text files, commit those, and rebuild the database from them.
