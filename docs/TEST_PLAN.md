# Test Plan

**System:** FST Case-Preparation Assistant
**Version:** 1.0 · 2026-11-21

Requirements: [SRS](SRS.md) · Design: [SDS](SDS.md)

---

## 1. Strategy

| Level | What it checks | Tool | When |
|---|---|---|---|
| Unit | Parsers, normalizers, ranking, metrics, citation checks | `pytest` | Every push (CI) |
| Data | Built corpus against the committed sources: counts, determinism, links | `pytest -m data` after `python -m fstlegal.corpus.build` | Every push (CI) |
| Integration | Pipelines against a live `llama-server` | `pytest -m model` | Locally, when the model runtime is present |
| System | Web app, cluster and reminders end to end | Scripted scenarios (Section 4) | From Phase 7 |
| Evaluation | Measured claims H1–H4 on gold sets | `python -m fstlegal.eval.*` | Each milestone; results in `docs/reports/` |

CI (`.github/workflows/ci.yml`) runs lint, builds the corpus from the committed sources and runs all tests not marked `model`. A change is merged only with CI passing.

**Environment:** reference laptop (i5-13th gen, 16 GB RAM, RTX 4050 6 GB, Windows 11), Python 3.11+, pinned runtime in `config/runtime.toml`. CI runs on Ubuntu with Python 3.12.

---

## 2. Test cases

Status: **Pass** (automated and passing), **Planned** (designed, phase not built yet).

### 2.1 Corpus (FR-1 to FR-9)

| ID | Requirement | Test | Automated in | Status |
|---|---|---|---|---|
| TC-01 | FR-1 | Unknown outcome wording is labelled, not fatal; outcomes map to fixed labels | `test_outcomes.py::test_normalize_outcome` | Pass |
| TC-02 | FR-2 | Each judgment appears once after grouping by site ID | `test_judgments.py::test_clean_dataset_loads` | Pass |
| TC-03 | FR-3 | Truncated endings are flagged; complete endings are not | `test_judgments.py::test_truncation_heuristic` | Pass |
| TC-04 | FR-4 | The ruling is found for at least 90% of complete judgments | `test_judgments.py::test_clean_dataset_loads` | Pass |
| TC-05 | FR-4 | Paragraph splitting follows the judgment's numbering and ignores numbered lists | `test_judgments.py::test_paragraphs_*`, `::test_numbered_list_*` | Pass |
| TC-06 | FR-5 | All 280 Article numbers of the Constitution are found | `test_constitution.py::test_every_article_number_is_found` | Pass |
| TC-07 | FR-5 | Article titles come from the margin; omitted Articles are flagged | `test_constitution.py::test_titles_from_the_margin`, `::test_omitted_article` | Pass |
| TC-08 | FR-5 | Footnote markers before an Article number are resolved correctly | `test_constitution.py::test_article_start` | Pass |
| TC-09 | FR-5 | All sections of the Service Tribunals Act and all 21 E&D Rules 2020 are found | `test_statutes.py::test_all_units_found` | Pass |
| TC-10 | FR-5 | Wrapped and unnumbered headings in scanned rules are handled | `test_statutes.py::test_wrapped_heading_is_joined`, `::test_unit_start` | Pass |
| TC-11 | FR-6 | 17 real spelling variants resolve to the right act and unit; years are not read as unit numbers | `test_laws.py::test_resolve` | Pass |
| TC-12 | FR-6 | Sub-references and ranges are kept | `test_laws.py::test_subreference_is_kept`, `::test_range` | Pass |
| TC-13 | FR-6 | Citation spellings share one key | `test_judgments.py::test_citation_spellings_share_a_key` | Pass |
| TC-14 | FR-7 | Every edge starts at an existing node | `test_build.py::test_corpus_contents` | Pass |
| TC-15 | FR-8 | Two builds from the same sources give the same content hash | `test_build.py::test_build_is_deterministic` | Pass |
| TC-16 | FR-9 | Quality report written on every build | Build output `data/build/quality_report.md` | Pass |

### 2.2 Retrieval and answering (FR-10 to FR-18)

| ID | Requirement | Test | Automated in | Status |
|---|---|---|---|---|
| TC-17 | FR-10 | User text cannot inject FTS5 syntax; stopword-only queries return nothing | `test_retrieval.py::test_fts_query_*` | Pass |
| TC-18 | FR-10 | Rank fusion rewards agreement between rankings | `test_retrieval.py::test_rrf_rewards_agreement` | Pass |
| TC-19 | FR-10 | "Right to fair trial" retrieves Article 10A | `test_retrieval.py::test_statute_search_finds_fair_trial_article` | Pass |
| TC-20 | FR-10 | A hidden judgment is never returned (no leakage in evaluation) | `test_retrieval.py::test_hidden_judgment_is_never_returned` | Pass |
| TC-21 | FR-11 | The brief has all five sections and every kept claim has sources | `test_baseline.py::test_end_to_end_with_fake_model` | Pass |
| TC-22 | FR-12, NFR-1 | Claims citing sources that were not retrieved are removed | `test_baseline.py::test_claims_without_valid_sources_are_dropped` | Pass |
| TC-23 | NFR-10 | Case papers reach the model only inside a block marked as data | `test_baseline.py::test_case_papers_are_marked_as_data` | Pass |
| TC-24 | FR-11 | Baseline answers a real question on the live model with only valid citations | `pytest -m model` | Planned (runtime downloading) |
| TC-25 | FR-13 | A claim paired with an unrelated passage is judged not supported | Verifier tests | Planned (Phase 6) |
| TC-26 | FR-14 | A question about a provision that does not exist gets an abstention | Gold set E4 | Planned (Phase 6) |
| TC-27 | FR-15 | "What does Article 10A say?" takes the single route; a long case file takes the RLM route | Router tests | Planned (Phase 5) |
| TC-28 | FR-16, NFR-9 | REPL code that opens a file, a socket or loops forever is stopped | Sandbox tests | Planned (Phase 5) |
| TC-29 | FR-17 | Every run has a trace with route, turns, code, tool calls and sub-calls | RLM tests | Planned (Phase 5) |
| TC-30 | FR-18 | A run over budget ends with an incomplete brief | RLM tests | Planned (Phase 5) |

### 2.3 Distribution (FR-19 to FR-24)

| ID | Requirement | Test | Status |
|---|---|---|---|
| TC-31 | FR-19 | Two workers never claim the same job (concurrent claim test) | Planned (Phase 7) |
| TC-32 | FR-20, NFR-11 | A job whose worker stops heartbeating returns to the queue and the run completes | Planned (Phase 7) |
| TC-33 | FR-21, NFR-13 | A new laptop joins with the pairing code in at most two interface steps | Planned (Phase 7) |
| TC-34 | FR-22 | A worker with a different model hash is refused; one with an old corpus updates first | Planned (Phase 7) |
| TC-35 | FR-24 | An interactive job is claimed before a queued background job | Planned (Phase 7) |
| TC-36 | NFR-7 | After jobs finish, a worker's disk holds no job text | Planned (Phase 7) |

### 2.4 Web app, notes and reminders (FR-25 to FR-33)

| ID | Requirement | Test | Status |
|---|---|---|---|
| TC-37 | FR-25 | Wrong password is rejected; a lawyer cannot open admin pages | Planned (Phase 8) |
| TC-38 | FR-26, NFR-8 | For every endpoint, user A gets "not found" for user B's matter, document, run and reminder | Planned (Phase 8) |
| TC-39 | FR-27 | A scanned PDF yields text through offline OCR | Planned (Phase 8) |
| TC-40 | NFR-10 | An uploaded paper instructing the model to read other matters has no effect on tool scope | Planned (Phase 8) |
| TC-41 | FR-30, FR-31 | A saved hearing note stores directions and the lead time | Planned (Phase 9) |
| TC-42 | FR-32, FR-33 | With the clock moved forward, the reminder appears on the right day with research attached | Planned (Phase 9) |
| TC-43 | NFR-14 | The full scenario runs with the internet disconnected | Planned (Phase 11) |

---

## 3. Evaluation

### 3.1 Gold sets

| Set | Built from | Measures |
|---|---|---|
| E1 Leave-one-out | Each judgment's own legal questions, with the judgment hidden; gold = the provisions it applied | Retrieval recall and ranking |
| E2 Outcome | Facts of non-truncated judgments without the ruling | Whether controlling provisions and similar decided cases are found |
| E3 Lawyer | Questions written and graded by practising lawyers | Usefulness, correctness, completeness |
| E4 Adversarial | Questions about provisions or citations that do not exist | Abstention |

### 3.2 Metrics and claims

| Claim | Metric | Comparison | Command |
|---|---|---|---|
| H1 Graph + RLM is more correct than RAG | Citation existence, citation support precision, unsupported-claim rate, Recall@k | Baseline vs RLM vs RLM + verifier, same model | `fstlegal.eval.retrieval_eval` (built); answer eval (Phase 6) |
| H2 More nodes, less time | Mean and p90 time per run; speed-up | 1 vs 2 nodes; control: 1 node with 2 server slots | Cluster benchmark (Phase 7) |
| H3 Better model, better results | All H1 metrics | Larger model, same pipeline | Model sweep runner |
| H4 Best fit for 6 GB | All H1 metrics plus tokens/s | RLM-Qwen3-8B Q4/Q5, Qwen3-8B Q4, Qwen3-4B Q8, Qwen3-14B Q4 with offload | Model sweep runner |

Every result is saved with the corpus hash, model hash and command that produced it.

### 3.3 Results so far

Leave-one-out retrieval at 28 judgments ([reports/retrieval_baseline.md](reports/retrieval_baseline.md)): BM25 recall@10 0.226, BM25 + graph 0.666, popularity control 0.726. The graph more than doubles keyword recall, but at this corpus size the popularity control is still ahead, so NFR-3 is not yet met. The test is re-run at full corpus size.

---

## 4. Entry and exit criteria

- **Entry for a phase's system tests:** the phase's unit tests pass in CI.
- **Exit for a phase:** every test case of that phase passes, and its exit criteria in the Implementation Plan are met.
- **Release (final evaluation):** all M requirements have a passing test, and every H1–H4 metric has a recorded value.

## 5. Traceability matrix

| Requirement | Test cases |
|---|---|
| FR-1 | TC-01 |
| FR-2 | TC-02 |
| FR-3 | TC-03 |
| FR-4 | TC-04, TC-05 |
| FR-5 | TC-06 to TC-10 |
| FR-6 | TC-11 to TC-13 |
| FR-7 | TC-14 |
| FR-8 | TC-15 |
| FR-9 | TC-16 |
| FR-10 | TC-17 to TC-20 |
| FR-11 | TC-21, TC-24 |
| FR-12 | TC-22 |
| FR-13 | TC-25 |
| FR-14 | TC-26 |
| FR-15 | TC-27 |
| FR-16 | TC-28 |
| FR-17 | TC-29 |
| FR-18 | TC-30 |
| FR-19 | TC-31 |
| FR-20 | TC-32 |
| FR-21 | TC-33 |
| FR-22 | TC-34 |
| FR-23 | TC-33 (cluster page shown) |
| FR-24 | TC-35 |
| FR-25 | TC-37 |
| FR-26 | TC-38 |
| FR-27 | TC-39 |
| FR-28 | TC-24 (rendered brief) |
| FR-29 | TC-37 (audit entries) |
| FR-30, FR-31 | TC-41 |
| FR-32, FR-33 | TC-42 |
| NFR-1 | TC-22, H1 |
| NFR-2 | H1 |
| NFR-3 | TC-20, H1 (E1) |
| NFR-4 | H2 |
| NFR-5 | H3 |
| NFR-6 | H4 |
| NFR-7 | TC-36 |
| NFR-8 | TC-38 |
| NFR-9 | TC-28 |
| NFR-10 | TC-23, TC-40 |
| NFR-11 | TC-32 |
| NFR-12 | Section 3.2 (commands recorded) |
| NFR-13 | TC-33 |
| NFR-14 | TC-43 |
| NFR-15 | CI |
