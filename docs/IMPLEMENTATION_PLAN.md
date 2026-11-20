# Implementation Plan

**Project:** On-premise legal case-preparation assistant for Federal Service Tribunal (FST) practice, built on a knowledge graph of judgments and statutes and a recursive language model whose sub-calls are distributed across laptops on a local network.

**Status:** Draft v1 · 2026-11-20

Architecture decisions referenced here are recorded in [DECISIONS.md](DECISIONS.md). The literature this design draws on is in [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md).

---

## 1. What we are building

A lawyer with an FST matter logs in to a web app on the office network, uploads the case papers (appeal, impugned order, show-cause notice, inquiry report) and asks a question. The system returns a case-preparation brief:

1. **Relevant law:** the statute sections and constitutional articles that govern the issue.
2. **Similar past cases:** FST judgments on the same provisions or facts, with what was decided and why.
3. **Likely opposing arguments:** what the department's counsel is likely to argue, drawn from how respondents argued in similar cases.
4. **Arguments in our favour:** the points that succeeded in comparable appeals, with the authority for each.
5. **Preparation checklist:** what to file, produce or be ready to answer at the next hearing.

Every statement in the brief carries a citation to a judgment in the corpus or a statute section. Statements the system cannot back with a source are removed or marked as unsupported.

A second layer handles hearings. After each hearing the lawyer records what the judge directed and their own view of it. A set number of days before the next hearing (set per case), the system reminds the lawyer and attaches research it has already run for each direction.

### Fixed constraints

| Constraint | Source |
|---|---|
| Fully offline: no internet at runtime, no email/WhatsApp | Requirement |
| FST cases only; Constitution of Pakistan (latest) plus the service statutes | Requirement |
| Multiple lawyers; each lawyer's matters, uploads and notes are private | Requirement |
| Correctness over speed | Requirement |
| Hardware today: one laptop (i5-13th gen, 16 GB RAM, RTX 4050 6 GB, Windows 11) | Environment |
| Additional laptops join by hand in one or two steps from a UI | Requirement |
| Recursive Language Model design from Zhang, Kraska & Khattab (arXiv:2512.24601) | Requirement |

### What the project must show

The evaluation is designed around four claims. Each needs measured evidence, not demonstration alone.

| ID | Claim | How it is tested |
|---|---|---|
| H1 | Graph retrieval with an RLM gives more correct and better-supported briefs than standard RAG on the same model | Baseline RAG vs routed graph + RLM on the same gold sets: citation existence, citation support, unsupported-claim rate, retrieval recall |
| H2 | Adding laptops reduces the time per run | Same runs on 1, 2, … nodes; time per run and speed-up. Controls: one node with parallel server slots, to separate the gain from batching on one GPU and the gain from more machines |
| H3 | Better hardware and a stronger model improve results without changing the system | Same pipeline with a larger model on stronger hardware (or a larger model offloaded to CPU on this laptop) |
| H4 | The chosen configuration is the best of the tested options that fit in 6 GB VRAM | Model and quantization sweep under the same pipeline and gold sets (Phase 3.8) |

H4 can only be shown against the candidates tested. The report will state that, list the candidates, and explain why each was chosen.

The RLM paper ran all model calls one after another and names asynchronous sub-calls as a likely way to cut runtime that it did not implement (Zhang et al., Observation 4). H2 tests that idea across machines.

---

## 2. Architecture overview

```
                 Lawyer browsers (any machine on the LAN)
                                 │  HTTPS (self-signed, hub only)
┌────────────────────────────────▼───────────────────────────────────┐
│ HUB LAPTOP                                                         │
│  Web app (FastAPI + React)   Auth & tenancy   Scheduler (reminders) │
│  RLM orchestrator ── REPL sandbox ── tools (search, graph, read)    │
│  Job queue (SQLite) ── lease manager ── worker registry            │
│  private.db (users, matters, uploads, notes)                        │
│  corpus.db (cases, statutes, chunks, edges, FTS5, embeddings)       │
│  Local worker ── llama-server (RLM-Qwen3-8B, Q4 GGUF)               │
└──────────────▲──────────────────────────────▲──────────────────────┘
               │ worker pulls jobs (HTTP)     │
   ┌───────────┴───────────┐      ┌───────────┴───────────┐
   │ WORKER LAPTOP         │ ...  │ WORKER LAPTOP         │
   │ worker agent          │      │ worker agent          │
   │ corpus.db (copy)      │      │ corpus.db (copy)      │
   │ llama-server (same    │      │ llama-server (same    │
   │ model hash)           │      │ model hash)           │
   └───────────────────────┘      └───────────────────────┘
```

**Request flow for one question:**

1. The lawyer submits a question on a matter. The hub creates a `run`.
2. The **router** (D-006) sends look-ups and short inputs to a single retrieval-backed call, and everything else to the RLM.
3. The **root call** (master) runs on the hub. Following the RLM design, the lawyer's question and case papers are not pasted into the prompt. They are loaded as variables in a Python REPL. The root model writes code that inspects them, calls retrieval tools and issues sub-calls (`llm_query`).
4. Each sub-call becomes a **job** in the queue with its prompt and any private context it needs. Batched sub-calls are queued together so several nodes can work on them at once.
5. Any free node (the hub's local worker or a remote worker) claims a job, retrieves from its own copy of the public corpus, runs the model and posts the answer back.
6. When the sub-call answers are in, the root call continues its loop and writes the brief.
7. The **verifier** checks every citation against the corpus and checks that the cited text supports the claim. Unsupported claims are removed or flagged.
8. The brief, its sources and the full call trace are stored on the run.

With one laptop, the same flow runs with only the local worker, so jobs are processed one after another.

### Repository layout (target)

```
├── dataset/            # scraping, enrichment and cleaning scripts
├── data/sources/       # official Constitution and statute texts
├── fstlegal/
│   ├── corpus/         # parsing, normalization, chunking, corpus build
│   ├── retrieval/      # BM25, embeddings, graph, hybrid ranking
│   ├── llm/            # llama-server client
│   ├── pipeline/       # baseline pipeline, router, RLM orchestrator
│   ├── verify/         # citation and support checks
│   ├── cluster/        # queue, leases, worker registry, pairing, worker agent
│   ├── app/            # FastAPI backend
│   └── eval/           # gold sets, metrics, experiment runner
├── web/                # frontend
├── tests/
└── docs/               # SRS, SDS, test plan, decisions, literature review, reports
```

---

## 3. Phases

Each phase lists its goal, tasks, outputs and **exit criteria**. A phase is done only when its exit criteria pass and are recorded in the test plan. Requirement IDs (`FR-x`, `NFR-x`) will be assigned in the SRS and back-filled here so every task traces to a requirement and a test.

| Phase | Name | Depends on |
|---|---|---|
| 0 | Project foundation | — |
| 1 | Corpus: cases and statutes | 0 |
| 2 | Knowledge graph and retrieval | 1 |
| 3 | Local model serving | 0 |
| 4 | Baseline RAG pipeline | 2, 3 |
| 5 | Recursive LM engine | 4 |
| 6 | Brief generation and verification | 5 |
| 7 | Distributed worker cluster | 5 |
| 8 | Web app, users and case papers | 4 (API), 6 |
| 9 | Hearing notes and reminders | 6, 8 |
| 10 | Evaluation | runs alongside 2–9; final round after 9 |
| 11 | Packaging and hardening | 7, 8, 9 |

Phases 2 and 3 can run in parallel. Phases 7 and 8 can run in parallel once Phase 5 is stable.

---

### Phase 0 — Project foundation

**Goal:** A repository that the three team members can work in without stepping on each other, with checks that run on every push.

**Tasks**
- 0.1 Restructure the repository into the package layout above. Keep `dataset/` as is.
- 0.2 Python 3.11+ project with `pyproject.toml`, pinned dependencies, and `ruff` + `pytest` configured.
- 0.3 GitHub Actions workflow: lint and unit tests on every push and pull request. Tests that need the model or GPU are marked and skipped in CI.
- 0.4 Branching rules: `main` protected, work on `feature/*`, `fix/*`, `chore/*` branches through pull requests.
- 0.5 `docs/` holds the SRS, SDS, test plan, decisions and literature review as Markdown, exported to Word/PDF for submission.
- 0.6 A `config/` file for paths, model settings and ports, with no secrets committed.

**Outputs:** project skeleton, CI workflow, contribution notes in the README.

**Exit criteria**
- A fresh clone installs with one command and `pytest` passes.
- CI runs on a pull request and reports status.

---

### Phase 1 — Corpus: cases and statutes

**Goal:** A clean, versioned `corpus.db` holding every usable FST judgment and the full text of the governing statutes, with consistent identifiers that the graph can rely on.

**1A. Judgments**
- 1.1 Keep `dataset/clean_dataset.py` as the gate from raw scrape to clean data. Extend its checks as the dataset grows: required fields, valid JSON, outcome mapping, ISO dates.
- 1.2 Detect truncated judgments automatically: text that ends mid-sentence or ends on the cited-cases list without an operative order. Keep `text_truncated` cases in the graph but exclude them from outcome statistics and outcome-based reasoning.
- 1.3 Deduplicate by `site_id`: one judgment reported in two reporters appears as two citation rows. Model this as one judgment node with several citations.
- 1.4 Scale the scrape and enrichment from 28 to about 2,000 judgments using the existing `parse_case_html.py` workflow. Track enrichment coverage per year.
- 1.5 Recover `appeal_number` and `decision_date` where the judgment text states them unambiguously; otherwise leave them empty.
- 1.6 Store each judgment's operative order (the final disposal paragraph) as a separate field, since outcome reasoning depends on it.

**1B. Statutes**
- 1.7 Collect the official text of the Constitution of the Islamic Republic of Pakistan 1973 (latest amended version, with the amendment number and date recorded at ingestion), and the service statutes cited in the corpus. The current data shows at least:
  - Service Tribunals Act 1973 and Service Tribunals (Procedure) Rules 1974
  - Civil Servants Act 1973
  - Civil Servants (Appeal) Rules 1977
  - Civil Servants (Appointment, Promotion and Transfer) Rules 1973
  - Civil Servants (Seniority) Rules 1993
  - Government Servants (Efficiency and Discipline) Rules 1973 and the Civil Servants (E&D) Rules 2020
  - General Clauses Act 1897 and Code of Civil Procedure 1908 (as referenced)
  - Departmental rules that recur (e.g. Police Service of Pakistan rules, WAPDA E&D Rules 1978), added as frequency in the full dataset justifies
- 1.8 Parse each statute into a hierarchy: act → part/chapter → section/article/rule → sub-section/clause. Each unit gets a stable ID such as `CONST-1973:art-10A` or `CSA-1973:s-13`.
- 1.9 Record amendment status where the source text shows it (inserted, substituted, omitted) and the version of the text ingested.

**1C. Normalization**
- 1.10 Build a statute alias table that maps every spelling in `laws_json` to a canonical act ID. The current 28 cases already show five spellings of the Service Tribunals Act and entries that are only a year or are empty.
- 1.11 Normalize provision strings ("Section 4", "S. 4", "4(1)(b)") to statute unit IDs. Unresolved references are kept in a review list, not guessed.
- 1.12 Normalize precedent citations (e.g. `2005 SCMR 890`) to a canonical form. Precedents not in the corpus become external citation nodes with no text.

**1D. Chunking**
- 1.13 Chunk judgments by paragraph number (FST judgments number their paragraphs), with the case header carried as metadata on every chunk.
- 1.14 Chunk statutes by section/article, never splitting a section across chunks unless it exceeds the size limit.

**Outputs:** `corpus.db` with tables for judgments, citations, statute units, aliases, chunks; a build script that recreates it from source files; a data-quality report.

**Exit criteria**
- `corpus.db` rebuilds from source in one command and its content hash is recorded.
- Every `laws_json` entry in the clean dataset resolves to a statute unit or appears in the unresolved list.
- The data-quality report lists counts of judgments, truncated judgments, missing fields, unresolved statute and precedent references.

---

### Phase 2 — Knowledge graph and retrieval

**Goal:** Given a question or a set of case papers, return the most relevant statute sections and judgment passages, with the graph relations that connect them.

**2A. Graph (D-003)**
- 2.1 Node types: `Judgment`, `Citation`, `StatuteUnit`, `Act`, `Judge`, `Keyword`, `ExternalCase`, `Outcome`.
- 2.2 Edge types, each with the source field it came from:
  - `Judgment —APPLIES→ StatuteUnit` (from `laws_json`)
  - `Judgment —CITES→ Judgment | ExternalCase` (from `precedents_json`)
  - `Judgment —DECIDED_BY→ Judge` (from `bench_members`)
  - `Judgment —HAS_OUTCOME→ Outcome`
  - `Judgment —TAGGED→ Keyword`
  - `StatuteUnit —PART_OF→ Act`, `StatuteUnit —REFERS_TO→ StatuteUnit` (cross-references inside statute text)
- 2.3 Graph builder writes edges to `corpus.db`; a loader builds the NetworkX graph in memory at startup.
- 2.4 Graph statistics: most-applied provisions, most-cited precedents, outcome rates per provision (excluding truncated judgments).

**2B. Retrieval**
- 2.5 Lexical search with SQLite FTS5 (BM25) over chunks.
- 2.6 Dense search: embed chunks with a local embedding model and run exact cosine search. Candidates to compare: BGE-M3 and Qwen3-Embedding-0.6B; pick by the Phase 2 retrieval evaluation.
- 2.7 Hybrid ranking: merge lexical and dense results with reciprocal rank fusion.
- 2.8 Graph expansion: from the top judgments, follow `APPLIES` and `CITES` edges to pull in the governing provisions and related judgments; from a statute unit, pull the judgments that applied it, ranked by similarity to the question.
- 2.9 Retrieval API used by every later phase: `search_cases`, `search_statutes`, `get_judgment`, `get_statute_unit`, `neighbors`, `cases_applying(unit_id)`.

**2C. Retrieval evaluation (feeds Phase 10)**
- 2.10 Leave-one-out gold set built from the corpus itself: for each judgment, use its `questions_json` and summary as the query, hide the judgment, and check whether retrieval returns the provisions it actually applied and the judgments it actually cited.
- 2.11 Metrics: Recall@k and nDCG@k for statute units and for judgments, for BM25, dense, hybrid and hybrid + graph.

**Outputs:** graph builder, retrieval package, retrieval evaluation report.

**Exit criteria**
- Graph rebuilds deterministically: same `corpus.db` gives the same node and edge counts.
- Retrieval evaluation report exists, and the chosen configuration is the best measured one, not assumed.

---

### Phase 3 — Local model serving (D-002)

**Goal:** RLM-Qwen3-8B running on the laptop through `llama-server`, reproducibly, with measured speed and memory.

**Tasks**
- 3.1 ~~Check the license~~ Done: the model is tagged MIT, its base Qwen3-8B is Apache-2.0 (D-007). The model card says it expects the upstream RLM scaffold and fixed system prompt.
- 3.2 Download the bf16 weights, convert to GGUF and quantize (start with Q4_K_M; compare one higher-precision quant if memory allows). Record the file hash.
- 3.3 Configure `llama-server`: GPU layer offload for 6 GB VRAM, context length, KV-cache type, number of slots (the root call and a sub-call may need to coexist on one node).
- 3.4 Benchmark on this laptop: prompt processing and generation tokens per second, peak VRAM and RAM, at the context sizes the RLM loop uses.
- 3.5 Fallback path: base Qwen3-8B GGUF with the same server config, selectable in `config/`.
- 3.6 Thin client in `llm/` with timeouts, retries and token accounting; every call logged with prompt, response, model hash and timings.
- 3.7 Quality check after quantization: run a fixed set of prompts on the quantized and (where it fits on CPU) unquantized model and compare.
- 3.8 **6 GB model sweep (H4):** run the same pipeline and gold sets with each candidate that fits this laptop, and choose the default from the results. Candidates:
  - RLM-Qwen3-8B at Q4_K_M and one higher quant (Q5_K_M or Q6_K) with more CPU offload
  - Base Qwen3-8B at the same quants (shows what the RLM fine-tune adds)
  - Qwen3-4B at Q8 (smaller model that fits fully in VRAM with a long context)
  - Qwen3-14B at Q4 with heavy CPU offload (shows the quality gain from a larger model at a speed cost; also feeds H3)
  - Other open models of similar size released by the time of the sweep, added if they fit and support the tool-use format
- 3.9 Check that the upstream RLM scaffold runs against `llama-server`'s OpenAI-compatible API (the upstream repo recommends vLLM).

**Outputs:** model files with hashes, server launch script, benchmark table, LLM client.

**Exit criteria**
- `llama-server` starts from one script and answers a health check.
- Benchmark table recorded in the SDS with measured numbers.
- License recorded as compatible with this project, or D-002 revisited.

---

### Phase 4 — Baseline RAG pipeline

**Goal:** A simple, working end-to-end system: retrieve, then answer in one model call with citations. It is the first demonstrable system and the baseline every later phase is compared against.

**Tasks**
- 4.1 Pipeline: question → hybrid + graph retrieval → one prompt containing the top passages with their citation IDs → answer that cites those IDs.
- 4.2 Output schema (JSON) for the brief's five sections, with each claim holding a list of citation IDs.
- 4.3 Basic citation check: every cited ID must be one of the passages given to the model.
- 4.4 Command-line entry point and a minimal API endpoint (`POST /ask`).
- 4.5 Run the Phase 2 gold set end to end and record answer-level metrics (Phase 10).

**Outputs:** baseline pipeline, CLI, API endpoint, baseline evaluation numbers.

**Exit criteria**
- A question about a real FST issue returns a structured brief whose citations all exist in the corpus.
- Baseline metrics recorded; this run is the reference point for Phases 5–6.

---

### Phase 5 — Recursive LM engine

**Goal:** The RLM loop from Zhang et al.: the root model works through a REPL holding the case material as variables, calls retrieval tools and issues sub-calls through the job queue.

**5.0 Router (D-006)**
- 5.0.1 Classify the question as a look-up (names a specific provision or case) or an analysis question.
- 5.0.2 Estimate input size: question + case papers + top retrieved passages, in tokens.
- 5.0.3 Look-ups and inputs under the threshold go to the Phase 4 single-call path; the rest go to the RLM. The threshold is set from the Phase 10 routing experiment.
- 5.0.4 The route and its reason are stored on the run.

**5A. REPL environment (D-007)**
- 5.1 Start from the upstream RLM code (github.com/alexzhang13/rlm) and keep its system prompt and conventions, which the fine-tuned model was trained on.
- 5.1a Variables loaded into the REPL: the question, the matter's case papers (as text, split by document), and run metadata. The full text is never pasted into the root prompt.
- 5.2 Tools exposed in the REPL: the Phase 2 retrieval API, `llm_query(prompt)` and a batched form that submits several sub-calls at once and waits for all of them.
- 5.3 Sandbox: model-written code runs in a separate process with a time limit, an output-size limit, no network, no file-system access and only whitelisted modules. Tool calls cross the process boundary through a small RPC layer, and every tool call is scoped to the current user and matter.
- 5.4 Recursion depth limited to 1 by default (sub-calls are plain model calls and cannot recurse). The reproduction study by Wang (arXiv:2603.02615) found that deeper recursion degraded results; depth 2 is kept as an experiment flag only.

**5B. Orchestration**
- 5.5 Root loop: send the REPL state, run the code the model returns, feed back truncated output, repeat until the model produces its final answer or a step/token budget is hit.
- 5.6 Sub-calls go through the queue (Phase 7 interface). Until Phase 7 lands, a local in-process executor implements the same interface and runs jobs one after another.
- 5.7 Every step (root turn, executed code, tool call, sub-call prompt and answer) is stored as a trace on the run so a lawyer or examiner can follow how the answer was reached.
- 5.8 Budgets per run: maximum root turns, maximum sub-calls, maximum tokens, wall-clock limit. Hitting a budget ends the run with a partial brief marked as incomplete.

**5C. Safety**
- 5.9 Uploaded documents can contain text that reads like instructions to the model. Case papers are treated as data: they are only reachable through REPL variables and quoted as such in sub-call prompts, and tools cannot reach other users' data whatever the model writes.

**Outputs:** `rlm/` package, sandbox, local executor, run traces.

**Exit criteria**
- The gold-set questions complete within budget without sandbox escapes or crashes.
- Results recorded side by side with the Phase 4 baseline.
- A deliberately malicious uploaded document cannot make a tool read another user's matter (test in the test plan).

---

### Phase 6 — Brief generation and verification

**Goal:** Turn the root model's output into the five-section brief and make sure every claim is backed by a source.

**Tasks**
- 6.1 Brief template and prompts for each section, including the opposing-counsel section: arguments respondents made in similar judgments, and how the tribunal answered them.
- 6.2 **Existence check:** every citation must resolve to a judgment, citation string or statute unit in the corpus. Unknown citations are removed and logged.
- 6.3 **Support check:** for each claim, a sub-call reads the cited passage and answers whether it supports the claim (supported / partly / not supported). Not-supported claims are removed; partly-supported claims are marked.
- 6.4 **Outcome guard:** claims about what was decided must come from the judgment's operative order and must not use `text_truncated` judgments.
- 6.5 **Abstention:** if nothing relevant is retrieved, the brief says so instead of producing general legal text.
- 6.6 Brief rendering for the web app with clickable sources that open the exact paragraph or section.

**Outputs:** `verify/` package, brief templates, rendered brief.

**Exit criteria**
- On the gold set, no brief contains a citation that does not exist in the corpus.
- Support-check precision measured on a hand-labelled sample (Phase 10).

---

### Phase 7 — Distributed worker cluster (D-001, D-005)

**Goal:** Additional laptops join from a UI in one or two steps and take sub-calls from the queue; a lost laptop does not lose work.

**7A. Queue**
- 7.1 `jobs` table: id, run id, kind, payload, priority, state (`queued`, `leased`, `done`, `failed`), attempts, lease owner, lease expiry, result, timings.
- 7.2 Claim with an atomic update; heartbeats extend the lease; an expired lease returns the job to `queued`; after N failed attempts the job is `failed` and the run is told.
- 7.3 Priorities: interactive runs first, background reminder research only when no interactive jobs are waiting.

**7B. Worker agent**
- 7.4 A small Windows program (packaged with the model server) that: checks the model hash, checks the corpus version, long-polls the hub for jobs, runs them, posts results and heartbeats.
- 7.5 Corpus sync: if the worker's `corpus.db` hash differs from the hub's, it downloads the current version from the hub before taking jobs.

**7C. Pairing (the "one or two steps")**
- 7.6 Admin opens **Cluster → Add worker** on the hub; the hub shows its address and a short one-time pairing code.
- 7.7 On the new laptop, the user runs the installer, enters the hub address and code (or picks the hub from a list if discovery is enabled). The worker receives its token and appears in the cluster page.
- 7.8 Only the hub needs one inbound port; the installer adds the Windows firewall rule for it on the hub. Workers make outbound connections only.

**7D. Cluster UI**
- 7.9 Cluster page: workers, status, current job, jobs done, average job time, model and corpus versions; buttons to pause or remove a worker.

**Outputs:** `cluster/` package, worker installer, cluster page.

**Exit criteria**
- With two laptops, a run's sub-calls are split across both (shown in the trace).
- Unplugging a worker mid-job: the job is requeued and the run finishes with the same answer quality.
- Adding a worker takes no command-line steps.

---

### Phase 8 — Web app, users and case papers

**Goal:** A multi-user web app where each lawyer sees only their own matters.

**Tasks**
- 8.1 Users and roles: `admin` (manages users and cluster) and `lawyer`. Passwords hashed with Argon2; session cookies; HTTPS with a self-signed certificate generated at install.
- 8.2 Tenancy: every private record (matter, document, note, run, reminder) has an owner; every query filters by owner at the data-access layer, not only in the UI. Optional sharing of a matter with named colleagues.
- 8.3 Matters: client, appeal number, department, stage, hearing history.
- 8.4 Case papers: upload PDF, DOCX and images; extract text (PDF text layer first, offline OCR with Tesseract for scans); split into documents and paragraphs; index in a per-user private index on the hub.
- 8.5 Ask page: question box tied to a matter; live progress showing root turns and sub-calls; the finished brief with sources.
- 8.6 Source viewer: judgment and statute text with the cited paragraph highlighted.
- 8.7 Run history per matter, with the trace available for review.
- 8.8 Audit log of logins, uploads and runs.

**Outputs:** `app/` backend, `web/` frontend.

**Exit criteria**
- Automated tests show user A cannot read, search or run against user B's matters through any API endpoint.
- A lawyer can upload case papers, ask a question and read the cited brief without command-line use.

---

### Phase 9 — Hearing notes and reminders

**Goal:** The system remembers what each judge directed and prepares the lawyer before the next hearing.

**Tasks**
- 9.1 Hearing note form per matter: hearing date, next hearing date, bench, list of directions (each with a type such as *produce document*, *address an argument*, *cite authority on a point*, *file reply*, *other*), free-text record of what the judge said, and the lawyer's own assessment of the hearing.
- 9.2 Reminder lead time set per matter (default chosen by the lawyer at matter creation).
- 9.3 Background research: when a note is saved, each research-type direction becomes a low-priority run (Phase 5–6) that executes when the cluster is idle.
- 9.4 Scheduler on the hub creates the reminder on the due date with the direction list, the lawyer's own notes and the finished research briefs.
- 9.5 Delivery without internet: an in-app notification centre and dashboard of upcoming hearings. Browser push services need the internet, so desktop pop-ups come from the open web app or from a small optional tray program on the lawyer's machine that polls the hub.
- 9.6 If background research has not finished by the reminder date, the reminder says so and the run is raised to normal priority.

**Outputs:** notes and reminders in `app/` and `web/`, scheduler, tray notifier.

**Exit criteria**
- With the system clock moved forward in a test, a reminder appears on the correct day with completed research attached.
- Reminders and notes follow the same tenancy rules as matters (tested).

---

### Phase 10 — Evaluation

**Goal:** Measured evidence for each claim the project makes: correct citations, fewer hallucinations than the baseline, and working distribution.

**Gold sets**
- E1 **Leave-one-out corpus set** (automatic, from Phase 2): queries from each judgment's questions and summary; gold = its applied provisions and cited judgments.
- E2 **Outcome set:** for non-truncated judgments, give the facts without the operative order and check whether the system identifies the controlling provisions and similar decided cases. Outcome prediction is reported but not presented as legal advice.
- E3 **Lawyer set:** a small number of realistic questions written and graded by practising lawyers, if available.
- E4 **Adversarial set:** questions about provisions or citations that do not exist; correct behaviour is to say so.

**Metrics**
- Retrieval: Recall@k, nDCG@k (statutes and judgments).
- Citation existence rate (target: every citation exists).
- Citation support precision and recall, on a hand-labelled sample.
- Unsupported-claim rate per brief.
- Abstention accuracy on E4.
- Lawyer ratings on E3: usefulness, correctness, completeness.
- System: time per run, jobs per run, speed-up from one node to two nodes, behaviour when a worker fails.

**Experiments**
- H1: Baseline RAG (Phase 4) vs RLM (Phase 5) vs RLM + verification (Phase 6), all on the same model.
- Routing: always single call vs always RLM vs routed; sweep the routing threshold.
- Retrieval variants: BM25 / dense / hybrid / hybrid + graph.
- Scaffold: upstream system prompt alone vs with legal-tool additions.
- Recursion depth 1 vs 2.
- H2: 1 node vs 2 nodes (and more if available), with one node with 2 server slots as a control. Report speed-up against the share of each run that must stay sequential (the root turns).
- H3: the same pipeline with a larger model, on stronger hardware if available or with CPU offload here.
- H4: the 6 GB model and quantization sweep from Phase 3.8.

**Outputs:** `eval/` runner that produces a report from a config; results tables for the final report.

**Exit criteria**
- Every metric above has a measured value and the command that produced it.
- Each SRS requirement maps to at least one test or metric (traceability matrix in the test plan).

---

### Phase 11 — Packaging and hardening

**Goal:** Someone other than the developers can install and run the hub and a worker.

**Tasks**
- 11.1 Hub installer: Python runtime, app, model, corpus, certificate, firewall rule, Windows service or startup entry.
- 11.2 Worker installer: worker agent and model server only.
- 11.3 Backup and restore of `private.db` and uploads.
- 11.4 Logging and an admin health page: model status, queue depth, worker health, disk space.
- 11.5 Corpus update procedure: rebuild `corpus.db`, bump version, workers sync automatically.
- 11.6 User guide and admin guide.

**Exit criteria**
- Clean-machine install of hub and one worker, following only the guides, succeeds.

---

## 4. Documentation deliverables and where they come from

| Deliverable | Content source | Phase |
|---|---|---|
| Software Requirements Specification | Section 1 of this plan, constraints, user stories for lawyers and admins, FR/NFR list | Written after this plan |
| Literature Review | [LITERATURE_REVIEW.md](LITERATURE_REVIEW.md) | Written with this plan |
| System Design Specification | Section 2, DECISIONS.md, component and data designs from Phases 1–9 | After SRS |
| Test Plan | Exit criteria of every phase, Phase 10 gold sets and metrics, traceability matrix | After SDS |
| Baseline implementation verification | Phase 4 results against the Phase 2 gold set | Phases 1–4 |
| Initial module implementation | Phase 1 corpus and Phase 2 retrieval modules with tests | Phases 1–2 |
| Version-controlled repository | This repository, CI from Phase 0 | Phase 0 onward |

## 5. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| RLM-Qwen3-8B license does not allow this use | Model choice changes | Check in Phase 3.1; fall back to base Qwen3-8B (D-002) |
| 4-bit model too weak for the root role | Poor plans and briefs | Measure in Phase 3.7 and Phase 10; try a higher quant with more CPU offload |
| Generation too slow with partial GPU offload | Long runs | Accepted (correctness first); background mode for reminder research; more nodes |
| Statute text sources incomplete or outdated | Wrong law cited | Record version and amendment at ingestion; show the version in the brief |
| Enrichment fields (`laws_json`, `precedents_json`) contain errors | Wrong graph edges | Normalization review list; spot-check sample in the data-quality report |
| Site serves truncated judgments | Wrong outcomes | `text_truncated` flag and outcome guard (Phases 1.2, 6.4) |
| Model-written code in the REPL misbehaves | Crashes or data access | Process sandbox with limits; tools scoped to user and matter (Phase 5.3) |
| Prompt injection through uploaded papers | Misleading output | Papers treated as data; tenancy enforced in tools, not prompts (Phase 5.9) |
| Hub laptop fails | System down | Backups (Phase 11.3); workers hold no private data |
