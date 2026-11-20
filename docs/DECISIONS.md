# Architecture Decisions

Decisions that are expensive to change later. New entries go at the bottom. Past entries are not rewritten; a reversed decision is marked `Superseded by D-NNN`.

---

## D-001: Deployment topology — one hub laptop, pull-based worker laptops
**Date:** 2026-11-20 · **Status:** Accepted

**Context:** Several lawyers must use one web app with private case data, fully offline. The project also commits to running recursive LLM calls across a cluster of edge laptops. Today there is one laptop; more must be able to join in one or two steps without network configuration.

| Option | Good | Bad | Effort |
|---|---|---|---|
| Each lawyer runs everything on their own laptop | No shared server; data isolation is physical | No cluster; every laptop needs a GPU; corpus updates go to every machine | Low |
| Hub + workers (hub hosts app, DB, queue; workers pull LLM jobs) | One place for users, data and scheduling; workers stay simple; only the hub needs an open port | Hub is a single point of failure | Medium |
| Peer-to-peer cluster (exo-style, model split across devices) | Can run models larger than one device | Layer-split inference is latency-bound on Wi-Fi; no natural home for users and data | High |
| Central server, no workers | Simplest multi-user setup | Drops the distributed-inference contribution | Low |

**Decision:** Hub + workers. The hub laptop runs the web app, authentication, SQLite database, job queue, scheduler and its own model instance. Worker laptops run a worker agent and a model instance; they connect out to the hub and pull jobs.
**Why:** It is the only option that gives multi-user isolation and task-level distribution together, with networking limited to one inbound port on the hub.
**Why not the others:** Standalone laptops lose the cluster. Peer-to-peer splits one model across machines, which an 8B model that fits on each laptop does not need. Central-only drops the distribution goal.
**Consequences:** Workers never accept inbound connections. User data never leaves the hub except as the text of a single job. Hub backup becomes important.
**Revisit if:** A single model no longer fits on one laptop, or the hub's uptime becomes a real problem for users.

---

## D-002: Model and serving runtime — RLM-Qwen3-8B as GGUF on llama.cpp
**Date:** 2026-11-20 · **Status:** Accepted

**Context:** Hardware is an i5-13th gen, 16 GB RAM and an RTX 4050 with 6 GB VRAM, on Windows. The design follows the Recursive Language Models paper (Zhang, Kraska, Khattab, arXiv:2512.24601), whose post-trained model RLM-Qwen3-8B is published as `mit-oasys/rlm-qwen3-8b-v0.1` (bf16 safetensors, about 16 GB). Correctness matters more than speed.

| Option | Good | Bad | Effort |
|---|---|---|---|
| llama.cpp `llama-server` with a 4-bit GGUF of RLM-Qwen3-8B | Native Windows + CUDA; GPU/CPU layer split fits 6 GB VRAM; OpenAI-compatible API; single binary for workers | We must convert and quantize the model ourselves | Medium |
| Ollama | Easiest install; same llama.cpp engine | Less control over slots, context and offload; adds a background service | Low |
| vLLM | High throughput | No native Windows support; needs the full model in VRAM | High |
| Base Qwen3-8B, not the RLM fine-tune | Ready-made GGUF builds exist | Not trained for the recursive REPL loop | Low |

**Decision:** Serve a 4-bit quantized GGUF of RLM-Qwen3-8B with llama.cpp `llama-server` on every node. Keep base Qwen3-8B as the fallback model. Pin the quantization and model hash so every node runs identical weights.
**Why:** It is the paper's own model, it fits the hardware with partial GPU offload, and the same binary can ship inside the worker installer.
**Why not the others:** Ollama hides the settings the RLM loop needs. vLLM does not run on this hardware or OS. Base Qwen3-8B is not trained for the recursion pattern.
**Consequences:** Phase 3 must verify the model license, conversion and quality after quantization. Token speed with partial offload is unmeasured; expect it to be slow.
**Revisit if:** The model's license forbids this use, quality after 4-bit quantization drops noticeably on our evaluation set, or a better RLM-trained small model is released.

---

## D-003: Graph construction — deterministic graph from structured fields, not LLM entity extraction
**Date:** 2026-11-20 · **Status:** Accepted

**Context:** Each enriched case already carries structured laws, precedents, bench members, keywords and questions. Microsoft GraphRAG builds its graph by running an LLM over every chunk to extract entities and community summaries. On a single 8B model, that indexing would be slow and would add extraction errors to the graph.

| Option | Good | Bad | Effort |
|---|---|---|---|
| Deterministic graph: nodes and edges built from structured fields and statute text | Every edge is traceable to a source field; fast to rebuild; no LLM extraction errors | Misses relations not present in the structured fields | Low |
| Microsoft GraphRAG pipeline | Community summaries for broad questions | LLM-heavy indexing; extracted entities can be wrong; harder to cite | High |
| Hybrid: deterministic core + optional LLM-derived edges marked as such | Core stays reliable; can add relations later | Two edge provenances to manage | Medium |

**Decision:** Build the core graph deterministically. Leave room for LLM-derived edges later, stored with a `derived_by` provenance field and never used as a citation source.
**Why:** The tool's main promise is correct citations. Every edge must point back to a judgment or statute that a lawyer can check.
**Why not the others:** Full GraphRAG makes the graph itself a possible source of hallucination. The hybrid is kept as a later extension, not a starting point.
**Consequences:** Statute names must be normalized to canonical acts and sections before the graph is built. Data quality of `laws_json` and `precedents_json` directly limits graph quality.
**Revisit if:** Evaluation shows that retrieval misses relevant cases that share no laws or precedents with the query case.

---

## D-004: Storage — SQLite for records, graph edges, full-text and vectors
**Date:** 2026-11-20 · **Status:** Accepted

**Context:** The dataset is already in SQLite (`dataset/fst.db`). At full scale the corpus is about 2,000 judgments plus the Constitution and service statutes. Every node keeps a full copy of the public corpus. No extra services should be needed on worker laptops.

| Option | Good | Bad | Effort |
|---|---|---|---|
| SQLite (tables + FTS5 for BM25) + exact vector search over embeddings stored in SQLite + NetworkX for traversal | One file per node; nothing to install; easy to ship to workers | Exact vector search gets slow at large scale | Low |
| Neo4j + a vector database | Rich graph queries | Java service on every node; heavier install; two stores to keep in sync | High |
| SQLite + FAISS/LanceDB index files | Fast approximate vector search | Second artifact to version and ship | Medium |

**Decision:** SQLite holds cases, statutes, chunks, edges, FTS5 indexes and embeddings. Vector search is exact (brute force) over embeddings loaded into memory. The graph is loaded into NetworkX for traversal. The public corpus is shipped to workers as a versioned, hashed SQLite file.
**Why:** It matches the existing code, keeps the worker install to a single file and binary, and the corpus is small enough for exact search (estimate, to be measured in Phase 2).
**Why not the others:** Neo4j is heavy to install and run on every laptop. A separate vector index adds sync work without a measured need.
**Consequences:** Private user data lives in a separate hub-only database, so the public corpus file can be copied to workers safely.
**Revisit if:** Measured vector search latency becomes a bottleneck, or the corpus grows beyond about 10× its current planned size.

---

## D-005: Job queue and worker protocol — SQLite-backed queue on the hub, HTTP pull with leases
**Date:** 2026-11-20 · **Status:** Accepted

**Context:** The master (root) model creates sub-calls that must be queued, picked up by any available node, retried if a node disappears, and collected for the final answer. Windows laptops, no internet, and setup must be simple.

| Option | Good | Bad | Effort |
|---|---|---|---|
| Jobs table in hub SQLite; workers long-poll an HTTP API; each claimed job has a lease that expires and requeues | No extra service; failure handling is explicit; the hub's local executor uses the same path | We write the lease logic ourselves | Low |
| Redis + Celery/RQ | Mature task queue | Redis has no native Windows build; an extra service to run | Medium |
| RabbitMQ | Robust messaging | Heavy install; more than this needs | High |
| ZeroMQ | Fast, no broker | No persistence; we would build retries and state on top | Medium |

**Decision:** Jobs live in a hub SQLite table with states `queued → leased → done | failed`. Workers authenticate with a token issued at pairing, long-poll `POST /jobs/claim`, send heartbeats to extend the lease, and post results. An expired lease puts the job back in the queue. The hub runs a local worker that uses the same API, so one laptop and many laptops behave the same way.
**Why:** It needs nothing beyond the hub's web server, survives worker loss, and keeps all job state where the web app can show progress.
**Why not the others:** Redis and RabbitMQ add services that are awkward on Windows. ZeroMQ would need the same state tracking built on top.
**Consequences:** Job payloads carry the prompt and retrieved context, so workers do not need access to private user data. Writes go through one hub process to avoid SQLite write contention.
**Revisit if:** Job volume causes measurable SQLite write contention, or workers must run on a different network than the hub.

---

## D-006: Query routing — single call for simple questions, RLM for complex ones
**Date:** 2026-11-20 · **Status:** Accepted

**Context:** The RLM paper reports that RLM performance is "slightly worse on smaller input lengths", which suggests a trade-off between a base model call and an RLM (Zhang et al., Observation 3). The reproduction by Wang (arXiv:2603.02615) found depth-1 RLMs worse than a plain model on simple retrieval. The paper itself has no router: the RLM decides through its own code whether to make sub-calls.

| Option | Good | Bad | Effort |
|---|---|---|---|
| Always RLM | One path; matches the paper | Slower and worse on simple look-ups | Low |
| Always single call (RAG) | Fast | Fails once case papers and retrieved judgments exceed what the model handles well | Low |
| Router: simple → single call, complex → RLM | Uses each where it is stronger; the threshold can be measured | One more component to test | Medium |

**Decision:** A router in front of the pipeline. A question goes to the single-call path when it is a look-up (a named provision, a named case) or when the question, case papers and retrieved passages fit under a token threshold. Everything else goes to the RLM. The threshold is a configuration value set from measurements on our evaluation set, not assumed.
**Why:** It follows the trade-off the paper itself reports, and makes it measurable on legal data.
**Why not the others:** Always-RLM pays the short-input penalty on every simple question. Always-single-call cannot handle long case files.
**Consequences:** Every run records its route and the reason. The evaluation compares always-single, always-RLM and routed.
**Revisit if:** Measurements show one path is at least as good on both simple and complex questions.

---

## D-007: RLM scaffold — upstream RLM code and system prompt, extended with legal tools
**Date:** 2026-11-20 · **Status:** Accepted

**Context:** The model card for `mit-oasys/rlm-qwen3-8b-v0.1` says it "was trained on trajectories produced using a fixed system prompt" and "assumes the environment/scaffold from our RLM repo" (github.com/alexzhang13/rlm). The paper's negative results note that prompts did not transfer well across models. License check: the model is tagged MIT and its base, Qwen3-8B, is Apache-2.0; both permit academic and commercial use. In the paper's implementation all model calls are blocking and sequential; the authors note asynchronous calls could cut runtime substantially but did not implement them.

| Option | Good | Bad | Effort |
|---|---|---|---|
| Use the upstream scaffold and system prompt; add legal tools as extra REPL functions; replace the sub-call function with a queue-backed one | Keeps the model in the setting it was trained for | Must track upstream changes | Medium |
| Write our own scaffold and prompts | Full control | The fine-tuned model sees an unfamiliar setting; likely quality loss | Medium |

**Decision:** Build on the upstream RLM code. Keep its system prompt and conventions, add retrieval tools as REPL functions with a short description appended to the prompt, and replace the blocking sub-call with one that submits to the job queue. Batched sub-calls are submitted together so they can run in parallel across nodes.
**Why:** The fine-tuned model is only an advantage if it runs in the scaffold it was trained on. Parallel, distributed sub-calls are exactly the part the paper leaves unimplemented.
**Why not the others:** A custom scaffold throws away the fine-tuning.
**Consequences:** Prompt additions must be tested against the unmodified prompt (ablation). The upstream repo recommends vLLM; we run it against llama.cpp's OpenAI-compatible server, which must be verified in Phase 3.
**Revisit if:** The upstream scaffold cannot run against llama.cpp, or the legal-tool additions measurably hurt the fine-tuned model.
