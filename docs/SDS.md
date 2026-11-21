# System Design Specification

**System:** FST Case-Preparation Assistant
**Version:** 1.0 · 2026-11-21

Requirements are in the [SRS](SRS.md). Design choices and the options compared are in [DECISIONS.md](DECISIONS.md) (D-001 to D-007).

---

## 1. Architecture

### 1.1 Deployment view (D-001)

```
                Lawyer browsers (LAN)
                        │ HTTPS
┌───────────────────────▼──────────────────────────────────────────┐
│ HUB                                                              │
│  Web API (FastAPI) ── Auth/tenancy ── Scheduler (reminders)      │
│  Router ── Baseline pipeline ── RLM orchestrator ── Verifier     │
│  Job queue + leases (SQLite) ── Worker registry ── Pairing       │
│  private.db (users, matters, papers, notes, runs, jobs)          │
│  corpus.db (judgments, statutes, chunks, edges, FTS5)            │
│  Local worker ── llama-server (chat model) + llama-server (embed)│
└────────────▲─────────────────────────────▲───────────────────────┘
             │ outbound HTTP (claim/heartbeat/result)
     ┌───────┴────────┐            ┌───────┴────────┐
     │ WORKER         │    ...     │ WORKER         │
     │ worker agent   │            │ worker agent   │
     │ corpus.db copy │            │ corpus.db copy │
     │ llama-server   │            │ llama-server   │
     └────────────────┘            └────────────────┘
```

- The hub is the only process that writes to either database.
- Workers make outbound connections only. The hub needs one inbound port.
- `corpus.db` is public data and is copied to workers. `private.db` never leaves the hub.

### 1.2 Request flow

1. `POST /matters/{id}/ask` creates a **run** in `private.db`.
2. The **router** (D-006) classifies the question and estimates input size, then picks a route.
3. **Single route:** the baseline pipeline retrieves sources and makes one model call.
   **RLM route:** the orchestrator runs the root loop; every `llm_query` becomes a job in the queue.
4. Nodes claim jobs, run them and post results; the root loop resumes when its batch is complete.
5. The **verifier** checks citation existence, then citation support (a sub-call per claim), then removes or marks claims.
6. The brief, sources and trace are stored on the run and returned.

### 1.3 Module view (repository layout)

| Package | Responsibility | Status |
|---|---|---|
| `dataset/` | Scraping, enrichment, `clean_dataset.py` (gate from raw scrape to clean data) | Built |
| `fstlegal/corpus/` | Parsing judgments, Constitution and statutes; law and citation normalization; chunking; building `corpus.db` | Built |
| `fstlegal/retrieval/` | Corpus access, BM25, embeddings, graph, rank fusion (`Retriever`) | Built |
| `fstlegal/llm/` | Client for `llama-server` with call logging | Built |
| `fstlegal/pipeline/` | Baseline pipeline (Phase 4); router and RLM orchestrator (Phase 5) | Baseline built |
| `fstlegal/verify/` | Citation existence and support checks | Phase 6 |
| `fstlegal/cluster/` | Queue, leases, worker registry, pairing, worker agent | Phase 7 |
| `fstlegal/app/`, `web/` | Web API and frontend | Phases 8–9 |
| `fstlegal/eval/` | Gold sets, metrics, experiment runners | Retrieval eval built |

---

## 2. Data design

### 2.1 Ingestion pipeline

```
scraped HTML ──parse_case_html.py──▶ fst.db ──export──▶ CSV ──clean_dataset.py──▶ fst_cases_clean.csv
                                                                                     │
data/sources/*.pdf ──constitution.py / statutes.py──┐                                │
                                                    ▼                                ▼
                                          fstlegal.corpus.build ──▶ corpus.db + quality_report.md
```

Re-ingesting the full scrape is the same two commands:

```
python dataset/clean_dataset.py --src <export.csv>
python -m fstlegal.corpus.build
```

### 2.2 `corpus.db` schema (implemented)

| Table | Key | Contents |
|---|---|---|
| `acts` | `id` (e.g. `CSA-1973`) | Title, unit kind, whether text is ingested, edition, notification that made it, the rules that replaced it and the date (D-008) |
| `amendments` | — | Per unit (or per act when the footnote marker was lost): kind, instrument, date made, date effective, year, footnote text (D-008) |
| `statute_units` | `id` (e.g. `CSA-1973:s-13`) | Act, number, title, Part, Chapter, text, footnotes (JSON), omitted flag |
| `judgments` | `id` = `J-<site_id>` | Parties, year, date, appeal number, bench, outcome, summary, questions, keywords, operative order, truncated flag, source URL, full text |
| `citations` | (`key`, `judgment_id`) | Every reported citation of a judgment and its normalized key |
| `chunks` | `id` (e.g. `J-237298#p4-6`, `CONST-1973:art-199#2`) | Retrieval units with paragraph range |
| `chunks_fts` | — | FTS5 index over chunk text (BM25) |
| `edges` | (`src`, `rel`, `dst`) | Graph edges with `source_field` (provenance) and detail |
| `unresolved_refs` | — | Law references that could not be mapped |
| `meta` | `key` | `content_hash` |

### 2.3 Identifiers

| Node | ID format | Example |
|---|---|---|
| Judgment | `J-<site id>` | `J-237298` |
| Statute unit | `<ACT>:<kind>-<number>` | `CONST-1973:art-10A`, `STA-1973:s-4`, `ED-2020:r-5` |
| Act | registry ID | `STA-1973` |
| External precedent | `EXT:<citation key>` | `EXT:2005 SCMR 890` |
| Judge | `JUDGE:<normalized name>` | `JUDGE:rooh-ul-amin-khan` |

Acts are defined once in `fstlegal/corpus/laws.py`, with patterns that map the many spellings found in judgments to one ID.

### 2.4 Graph (D-003)

| Edge | From → To | Source field |
|---|---|---|
| `APPLIES` | Judgment → statute unit or act | `laws_json` |
| `CITES` | Judgment → judgment or external case | `precedents_json` |
| `DECIDED_BY` | Judgment → judge | `bench_members` |
| `HAS_OUTCOME` | Judgment → outcome | `outcome` |
| `TAGGED` | Judgment → keyword | `keywords` |
| `PART_OF` | Statute unit → act | statute parse |

The graph is loaded into NetworkX at startup (`CorpusGraph`). Edges are never generated by the model.

### 2.5 `private.db` schema (designed, Phase 7–9)

| Table | Contents |
|---|---|
| `users` | id, name, role (`admin`/`lawyer`), Argon2 password hash |
| `matters` | id, owner, client, appeal number, department, stage; `matter_shares` for sharing |
| `documents` | id, matter, file name, extracted text, OCR flag |
| `doc_chunks` | private chunks and FTS index, scoped by matter |
| `hearings` | matter, date, next date, bench, remarks, own assessment, reminder lead days |
| `directions` | hearing, type (`produce_document`, `address_argument`, `cite_authority`, `file_reply`, `other`), text, research run |
| `runs` | id, matter, owner, question, route, status, brief (JSON), trace (JSON), timings |
| `jobs` | id, run, kind, payload, priority, state, attempts, lease owner, lease expiry, result, timings |
| `workers` | id, name, token hash, model hash, corpus hash, last heartbeat, status |
| `reminders` | matter, hearing, due date, state |
| `audit_log` | time, user, action, object |

Every query on a private table goes through a data-access function that takes the current user and adds the ownership condition (FR-26).

---

## 3. Component design

### 3.1 Corpus build (`fstlegal/corpus/`)
- `judgments.py`: groups rows by site ID, splits paragraphs by following the judgment's own numbering (a marker starts a paragraph only if it continues the sequence), detects truncation from missing closing phrases, and extracts the operative order from the closing sentences.
- `constitution.py`: reads the PDF line by line. Margin titles (right on odd pages, left on even), the body column and footnotes are told apart by position. Footnote markers printed before an Article number are resolved by which reading continues the sequence.
- `statutes.py`: parses Pakistan Code PDFs into sections, joins headings wrapped across lines, and for scanned Gazette text recovers lost rule numbers from headings.
- `estacode.py`: cuts each set of rules out of ESTACODE 2021 by page range and its closing `[Authority: ...]` line, and ties each amendment footnote to its rule through the page's symbol markers (`*`, `**`, `@`).
- `amendments.py`: reads kind, instrument, date and effective date from a footnote (D-008).
- `laws.py`: act registry and reference resolver; the act decides the unit kind, so a judgment's "Rule 4" of an Act still maps to section 4.
- `chunking.py`: judgment chunks follow paragraph boundaries (up to 350 words); statute chunks are one unit each, split at sub-sections if long, each starting with the unit header.
- `build.py`: writes all tables, then the FTS index, then a content hash over all rows in a fixed order (FR-8), then the quality report.

### 3.2 Retrieval (`fstlegal/retrieval/`)
- **BM25** (`lexical.py`): user text becomes a quoted OR-query of non-stopword terms, so it can never be read as FTS5 syntax.
- **Dense** (`dense.py`): embeddings from `llama-server --embedding` (Qwen3-Embedding-0.6B), exact cosine search, vectors cached per corpus hash and model.
- **Graph** (`graph.py`): related judgments score shared provisions and precedents, weighted by `1 / number of judgments` sharing them, so near-universal provisions count little.
- **Fusion** (`hybrid.py`): reciprocal rank fusion (k = 60). In graph modes, judgments linked to the top text hits are fused into case search, and the provisions applied by the top cases are fused into statute search. Modes: `bm25`, `dense`, `hybrid`, `bm25+graph`, `hybrid+graph`.

- **Versions** (`versions.py`, D-008): for a judgment, the changes to each provision it applied that came after its decision date (amendments) or at any time (repeal of the rules), each with the later judgments that applied the new wording.

### 3.3 Baseline pipeline (`fstlegal/pipeline/baseline.py`)
Retrieves 6 statute units and 4 judgments, labels them `[S1]…`, `[C1]…`, adds a `LAW SINCE` note to each judgment whose law has changed, and calls the model once with a JSON schema that forces the six-section brief with a `sources` list on every claim (`llama-server` constrains generation to the schema). Claims citing no retrieved source are removed. Case papers are passed inside a block marked as data.

### 3.4 Router (Phase 5, D-006)
- Look-up: the question names a specific unit (`Article 10A`, `section 4`) or citation → single route.
- Otherwise estimate tokens of question + case papers + top passages. Under the threshold → single route; above → RLM.
- The threshold is set from the routing experiment, not assumed. Route and reason are stored on the run.

### 3.5 RLM orchestrator (Phase 5, D-007)
- Built on the upstream RLM code and its system prompt, which RLM-Qwen3-8B was trained with.
- REPL variables: `question`, `case_papers` (dict of document → text), `matter_id`.
- REPL functions: `search_statutes`, `search_cases`, `get_unit`, `get_judgment`, `neighbors`, `llm_query(prompt)`, and a batched `llm_query_batch(prompts)`.
- `llm_query` writes a job and waits. A batch writes all its jobs at once, which is what lets several nodes work in parallel; the paper's own implementation ran these calls one at a time.
- Depth 1: sub-calls are plain model calls (Wang 2026 found depth 2 degrades results).
- Sandbox: the REPL runs in a child process with a wall-clock limit, an output-size limit, a module whitelist and no file or network access. Tool calls go to the parent over a pipe, and the parent applies the user and matter scope.
- Budgets per run: root turns, sub-calls, tokens, wall clock (FR-18).

### 3.6 Verifier (Phase 6)
1. **Existence:** every source label resolves to a statute unit or judgment in `corpus.db` (or a private document of the same matter).
2. **Support:** for each claim, a sub-call receives the claim and the cited passage and answers `supported` / `partly` / `not_supported` in a JSON schema.
3. **Outcome guard:** claims about what a judgment decided must cite a judgment whose text is not truncated, and are checked against its operative order.
4. Not-supported claims are removed; partly-supported ones are marked; if nothing survives, the brief says no supported answer was found (FR-14).

### 3.7 Job queue and workers (Phase 7, D-005)

**Job states:** `queued → leased → done`, or `leased → queued` when the lease expires, or `failed` after N attempts.

**Worker API (hub):**

| Endpoint | Purpose |
|---|---|
| `POST /cluster/pair` | Exchange a one-time pairing code for a worker token |
| `POST /cluster/jobs/claim` | Long-poll; atomically lease the highest-priority queued job |
| `POST /cluster/jobs/{id}/heartbeat` | Extend the lease |
| `POST /cluster/jobs/{id}/result` | Store the result; wake the waiting run |
| `GET /cluster/corpus` | Download the current `corpus.db` (when the worker's hash differs) |

A worker sends its model hash and corpus hash with every claim; the hub refuses mismatches (FR-22). The hub's own local worker uses the same API, so one node and many nodes follow the same code path.

**Job payload:** `{kind: "chat", messages, json_schema?, max_tokens, temperature}`. Private context is included in the messages; workers keep nothing after posting the result (NFR-7).

### 3.8 Reminders (Phase 9)
- The scheduler checks daily for hearings whose `next_date - lead_days` is today and creates a reminder.
- Saving a hearing note creates a background run (low priority) for each research-type direction.
- Delivery is offline: the in-app notification centre, plus a browser notification while the app is open. An optional tray program on the lawyer's machine polls the hub for pop-ups.

---

## 4. Model serving (D-002)

| Role | Model | Runtime |
|---|---|---|
| Root and sub-calls | RLM-Qwen3-8B, 4-bit GGUF converted locally from the official weights (`mit-oasys/rlm-qwen3-8b-v0.1`, MIT) | `llama-server`, partial GPU offload |
| Fallback and comparison | Qwen3-8B Q4_K_M (official GGUF, Apache-2.0) | same |
| Embeddings | Qwen3-Embedding-0.6B Q8_0 (official GGUF) | `llama-server --embedding` |

Versions are pinned in `config/runtime.toml` (llama.cpp build tag, model repository revisions); `scripts/fetch_runtime.py` downloads them. Each node runs the same files.

---

## 5. Security and privacy

| Threat | Control |
|---|---|
| A user reads another user's matter | Ownership condition in every data-access function; tests on every endpoint (NFR-8) |
| Model-written code misbehaves | Process sandbox with limits; tools scoped by the parent (NFR-9) |
| Instructions hidden in uploaded papers | Papers are only REPL data or marked data blocks; tool scope does not depend on prompts (NFR-10) |
| A rogue machine joins as a worker | Pairing code issued by an administrator; per-worker token; tokens revocable |
| Eavesdropping on the LAN | HTTPS with a certificate generated at install |
| Private data left on workers | Jobs carry only the text they need; workers keep no job data after the result is posted |

---

## 6. Requirement traceability (design → requirements)

| Component | Requirements |
|---|---|
| `clean_dataset.py`, `corpus/judgments.py` | FR-1, FR-2, FR-3, FR-4 |
| `corpus/constitution.py`, `corpus/statutes.py` | FR-5 |
| `corpus/laws.py`, `corpus/citations.py` | FR-6 |
| `corpus/build.py` | FR-7, FR-8, FR-9 |
| `retrieval/` | FR-10, NFR-3 |
| `pipeline/baseline.py` | FR-11, FR-12, FR-35, NFR-1 |
| `corpus/estacode.py`, `corpus/amendments.py`, `retrieval/versions.py` | FR-34, FR-35 |
| Router, RLM orchestrator | FR-15 to FR-18, NFR-9, NFR-10 |
| Verifier | FR-12, FR-13, FR-14, NFR-2 |
| Cluster | FR-19 to FR-24, NFR-4, NFR-7, NFR-11, NFR-13 |
| Web app | FR-25 to FR-29, NFR-8, NFR-14 |
| Scheduler, notes | FR-30 to FR-33 |
| `eval/`, `config/runtime.toml` | NFR-5, NFR-6, NFR-12 |
