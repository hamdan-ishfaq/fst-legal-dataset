# Software Requirements Specification

**System:** FST Case-Preparation Assistant: an on-premise legal analysis tool for Federal Service Tribunal practice, using a knowledge graph and distributed recursive language models.
**Version:** 1.0 · 2026-11-21

Related: [Literature Review](LITERATURE_REVIEW.md) · [System Design](SDS.md) · [Test Plan](TEST_PLAN.md) · [Decisions](DECISIONS.md) · [Implementation Plan](IMPLEMENTATION_PLAN.md)

---

## 1. Introduction

### 1.1 Purpose
This document states what the system must do and how well. It is the reference for the design (SDS) and for the tests (Test Plan), which trace back to the requirement IDs below.

### 1.2 Scope
Lawyers preparing Federal Service Tribunal (FST) appeals spend much of their time finding the governing provisions, locating comparable judgments, anticipating the department's arguments and tracking what the bench directed at each hearing. The system does this research for them, offline, with every statement tied to a judgment or statute section they can check. Its parts are:

- a corpus of FST judgments, the Constitution of Pakistan and the service statutes, linked into a knowledge graph;
- a question-answering pipeline that routes simple questions to a single model call and complex ones to a recursive language model (RLM);
- a job queue that spreads RLM sub-calls across laptops on the office network;
- a multi-user web application with private matters, uploaded case papers, hearing notes and reminders.

Out of scope: courts other than the FST, filing documents with the Tribunal, Urdu-language judgments, and any use of the internet at runtime.

### 1.3 Definitions

| Term | Meaning |
|---|---|
| FST | Federal Service Tribunal, established under Article 212 of the Constitution and the Service Tribunals Act 1973 |
| Judgment | A reported FST decision in the corpus |
| Statute unit | One Article, section or rule of a statute |
| Matter | A lawyer's own case being prepared |
| Brief | The system's answer: relevant law, similar cases, likely opposing arguments, arguments in favour, preparation checklist |
| RLM | Recursive Language Model (Zhang, Kraska, Khattab, 2025): a root model that works through a REPL and issues sub-calls to the model |
| Hub | The laptop running the web app, database, queue and scheduler |
| Worker | A laptop that runs the model and takes sub-calls from the hub's queue |

### 1.4 References
Zhang et al., *Recursive Language Models*, arXiv:2512.24601; Wang, *Reproducing Recursive Language Models*, arXiv:2603.02615; full list in the Literature Review.

---

## 2. Overall description

### 2.1 Product perspective
A self-contained system installed on the lawyers' own machines. No cloud service is used. The hub laptop holds all private data. Worker laptops only add model capacity.

### 2.2 Users

| User | Needs |
|---|---|
| Lawyer | Ask questions about a matter, upload case papers, record hearings, receive reminders, read and check the sources behind every answer |
| Administrator | Create user accounts, add and remove worker laptops, update the corpus, back up data |
| Examiner / researcher | Reproduce the evaluation results from the repository |

### 2.3 Operating environment
- Hub and workers: Windows 11 laptops. Reference hardware: Intel i5 13th gen, 16 GB RAM, NVIDIA RTX 4050 with 6 GB VRAM.
- Lawyers use a current web browser on any machine on the same local network.
- Model runtime: llama.cpp `llama-server` (D-002).

### 2.4 Constraints
- C1: Fully offline at runtime; no email, messaging or cloud APIs.
- C2: Only FST judgments; statute text from official sources, with the edition recorded.
- C3: One open-weight model family on every node, pinned by file hash.
- C4: The model must fit a 6 GB GPU with partial CPU offload.

### 2.5 Assumptions
- Judgments are supplied by the project's scraping and enrichment step in the existing CSV/SQLite format.
- All nodes are on one local network, and the hub can open one inbound port.

---

## 3. Functional requirements

Priority: **M** must (needed for the system to meet its purpose), **S** should, **C** could. "Phase" refers to the Implementation Plan.

### 3.1 Corpus and knowledge graph

| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-1 | Import judgments from the cleaned dataset, keeping only those with judgment text and enrichment fields, and report rows dropped with reasons. | M | 1 |
| FR-2 | Group the different citations of one judgment into a single judgment record. | M | 1 |
| FR-3 | Detect judgments whose text is truncated, and exclude them from any statement about outcomes. | M | 1 |
| FR-4 | Extract the operative order (ruling) of each complete judgment. | M | 1 |
| FR-5 | Parse the Constitution and each service statute into units (Article, section, rule) with number, title and amendment footnotes, and record the edition used. | M | 1 |
| FR-6 | Map every free-text law reference in a judgment to a canonical act and unit, and list any that cannot be mapped. | M | 1 |
| FR-7 | Build a graph whose edges (applies, cites, decided by, has outcome, tagged, part of) each record the source field they came from. | M | 2 |
| FR-8 | Rebuild the corpus deterministically: the same sources produce the same content hash. | M | 1 |
| FR-9 | Produce a data-quality report on every build. | S | 1 |

### 3.2 Retrieval and answering

| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-10 | Retrieve statute units and judgment passages for a question by keyword, embedding and graph search, alone or combined. | M | 2 |
| FR-11 | Produce a brief with six sections, where every claim lists the sources it rests on. | M | 4 |
| FR-12 | Remove any claim whose cited sources were not retrieved, or do not exist in the corpus. | M | 4, 6 |
| FR-13 | Check that each cited passage supports its claim; remove unsupported claims and mark partly supported ones. | M | 6 |
| FR-14 | Say so when nothing relevant is found, instead of answering from general knowledge. | M | 6 |
| FR-15 | Route look-up and short questions to a single model call, and complex questions to the RLM (D-006). | M | 5 |
| FR-16 | Run the RLM root model with the question and case papers held as REPL variables, with retrieval tools and sub-calls available (D-007). | M | 5 |
| FR-17 | Store the full trace of each run: route, root turns, executed code, tool calls, sub-call prompts and answers. | M | 5 |
| FR-18 | Stop a run that exceeds its step, sub-call, token or time budget, and mark the partial brief as incomplete. | S | 5 |
| FR-34 | Record the amendment history of every statute unit (what changed, by which instrument, on which date) and which sets of rules replaced others, from the official texts. | M | 1 |
| FR-35 | For each judgment cited in a brief, state which version of each provision it applied (by decision date), every later change with its date, and the later judgments that applied the new wording, or that none has; the model's view of whether the change would alter the result is shown labelled as opinion, not authority. | M | 4 |

### 3.3 Distributed execution

| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-19 | Queue every sub-call as a job that any connected node can claim. | M | 7 |
| FR-20 | Return a job to the queue when its node stops sending heartbeats, and fail it after a set number of attempts. | M | 7 |
| FR-21 | Add a worker laptop from the web interface with a one-time pairing code, with no command-line steps. | M | 7 |
| FR-22 | Refuse jobs on a worker whose model hash or corpus version differs from the hub's, and update its corpus copy from the hub. | M | 7 |
| FR-23 | Show each worker's status, current job and throughput on a cluster page. | S | 7 |
| FR-24 | Run interactive questions before background research jobs. | S | 7 |

### 3.4 Users, matters and documents

| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-25 | Authenticate users, with administrator and lawyer roles. | M | 8 |
| FR-26 | Restrict every matter, document, note, run and reminder to its owner (and anyone the owner shares it with), enforced in the data-access layer. | M | 8 |
| FR-27 | Accept PDF, DOCX and image uploads of case papers, and extract their text offline (with OCR for scans). | M | 8 |
| FR-28 | Show the brief with each source openable at the cited paragraph or section. | M | 8 |
| FR-29 | Keep an audit log of logins, uploads and runs. | S | 8 |

### 3.5 Hearing notes and reminders

| ID | Requirement | Priority | Phase |
|---|---|---|---|
| FR-30 | Record, for each hearing, the date, next date, bench, the directions given (with a type), the judge's remarks, and the lawyer's own assessment. | M | 9 |
| FR-31 | Let the lawyer set how many days before a hearing the reminder appears, per matter. | M | 9 |
| FR-32 | Turn each research-type direction into a background run that executes when the cluster is idle. | M | 9 |
| FR-33 | Show the reminder in the app on the due day, with the directions, the lawyer's notes and the finished research attached; raise unfinished research to normal priority. | M | 9 |

---

## 4. Non-functional requirements

| ID | Category | Requirement | How it is measured |
|---|---|---|---|
| NFR-1 | Correctness | No citation in a brief points at a judgment or statute unit outside the corpus. | Citation existence rate on the gold sets: target 100% |
| NFR-2 | Correctness | The share of claims not supported by their cited source is lower for the full system than for the baseline. | Unsupported-claim rate, baseline vs RLM + verification (H1) |
| NFR-3 | Retrieval | Graph-augmented retrieval beats keyword-only retrieval and a popularity control on the leave-one-out set at full corpus size. | Recall@k, nDCG@10 (H1) |
| NFR-4 | Scalability | Adding a worker laptop reduces mean time per RLM run on the same question set. | Speed-up from 1 to 2 nodes, with a one-node two-slot control (H2) |
| NFR-5 | Portability of the model | Swapping the model for a larger one changes only configuration. | Same pipeline run with a larger model (H3) |
| NFR-6 | Model choice | The default model is the best of the tested candidates that fit 6 GB VRAM. | Model and quantization sweep (H4) |
| NFR-7 | Privacy | No private data leaves the hub except the text of a single job sent to a worker; workers store none of it. | Inspection test of worker storage after jobs |
| NFR-8 | Isolation | A user cannot read, search or run against another user's matter through any endpoint. | Automated access tests on every endpoint |
| NFR-9 | Security | Model-written REPL code runs in a separate process with no network or file access and with time and output limits. | Sandbox escape tests |
| NFR-10 | Robustness | Uploaded text cannot change which data the tools can reach. | Prompt-injection test documents |
| NFR-11 | Reliability | Losing a worker mid-run does not lose the run. | Disconnect test during a run |
| NFR-12 | Reproducibility | Every reported metric can be regenerated with one documented command from the repository. | Commands listed in each report |
| NFR-13 | Usability | Adding a worker takes at most two steps in the interface. | Usability walkthrough |
| NFR-14 | Offline | The system runs with the network cable unplugged from the internet (LAN only). | Offline end-to-end test |
| NFR-15 | Maintainability | Code passes lint and unit tests on every push. | CI status |

Latency is not a requirement beyond completing within the run budget: correctness takes priority over speed (C4).

---

## 5. Use cases

**UC-1 Ask about a matter.** The lawyer opens a matter, types a question and submits. The system routes the question, runs retrieval and the model, verifies the citations and shows the brief with sources and the run trace. *Covers FR-10 to FR-18, FR-28.*

**UC-2 Upload case papers.** The lawyer uploads the appeal, the impugned order and the inquiry report. The system extracts the text and makes it available to questions on that matter only. *FR-26, FR-27.*

**UC-3 Record a hearing.** After a hearing, the lawyer fills the hearing form, including the bench's directions and their own assessment, and sets the reminder lead time. The system queues background research for research-type directions. *FR-30 to FR-32.*

**UC-4 Receive a reminder.** On the due day, the reminder appears with the directions and finished research. *FR-33.*

**UC-5 Add a worker.** The administrator opens Cluster → Add worker and gets a pairing code. On the new laptop, the installer asks for the hub address and code. The worker checks its model and corpus versions and starts taking jobs. *FR-21 to FR-23.*

**UC-6 Update the corpus.** The administrator imports a new batch of judgments and rebuilds the corpus. Workers update automatically before taking new jobs. *FR-1 to FR-9, FR-22.*

---

## 6. Requirement status at mid-term

| Requirement | Status |
|---|---|
| FR-1 to FR-9 | Implemented and tested (corpus build) |
| FR-10 | Implemented: keyword, graph and fusion tested; embedding search implemented, awaiting the model server for measurement |
| FR-11, FR-12 | Implemented in the baseline pipeline; tested with a stub model and verified live on Qwen3-8B over 28 judgments (`reports/baseline_verification.md`) |
| FR-34, FR-35 | Implemented and tested: amendment history from ESTACODE and Pakistan Code footnotes; law-change notes and labelled opinion in the brief |
| FR-16, FR-17, FR-18 | Implemented and tested: RLM loop, sandboxed REPL, legal tools, run trace, budgets |
| FR-19, FR-20, FR-24 | Implemented and tested on one laptop: job queue with leases, retries and priorities; local workers |
| FR-13 to FR-15, FR-21 to FR-23, FR-25 to FR-33 | Designed (SDS); scheduled in Implementation Plan Phases 5 to 9 |
| NFR-1, NFR-12, NFR-15 | In place (citation existence check, documented commands, CI) |
| NFR-3 | Measured at 28 judgments (see `reports/retrieval_baseline.md`); to be re-measured at full size |
