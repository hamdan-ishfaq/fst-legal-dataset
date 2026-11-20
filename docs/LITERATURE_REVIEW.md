# Literature Review

**Project:** On-premise legal case-preparation assistant for Federal Service Tribunal practice using a knowledge graph and distributed recursive language models.

**Status:** Draft v1 · 2026-11-20

---

## 1. Scope

The system combines five lines of work: retrieval-augmented generation (RAG), graph-based retrieval, legal AI, recursive and decomposed language-model inference, and local or distributed inference on consumer hardware. This review covers each in turn, then the work on hallucination and evaluation that shapes how the system is tested, and ends with the gap this project addresses.

---

## 2. Retrieval-augmented generation

**Foundations.** Lewis et al. [1] introduced RAG: a generator conditioned on passages fetched from an external index, so that knowledge can be updated without retraining and answers can point to their sources. Later work showed that adding retrieved text is not enough on its own. Liu et al. [2] found that models use information at the start and end of a long context far better than information in the middle, so packing more passages into one prompt does not reliably improve answers. That finding motivates both careful ranking and approaches that avoid one very long prompt.

**Adaptive retrieval and self-checking.** Self-RAG [3] trains a model to decide when to retrieve and to critique its own output against the retrieved passages. Chain-of-Verification [4] has the model draft an answer, plan verification questions, answer them independently and revise. Both point to the same design principle used here: generation and checking should be separate steps.

**Hierarchical retrieval.** RAPTOR [5] builds a tree of recursive summaries over chunks so that questions can be answered at different levels of detail. It is relevant to long judgments, where both a specific paragraph and the overall holding matter.

**Relevance to this project.** The baseline pipeline (Implementation Plan, Phase 4) is a standard RAG system. It is the reference point against which the recursive and graph-based components are measured.

---

## 3. Graph-based retrieval

**GraphRAG.** Edge et al. [6] build an entity graph from a corpus with an LLM, detect communities in it and pre-summarize each community. Their results show gains over plain vector RAG on broad "sensemaking" questions over large corpora. The cost is an indexing stage that runs an LLM over the whole corpus, and a graph whose entities and relations are themselves model outputs.

**Lighter graph methods.** LightRAG [7] combines graph structure with vector retrieval at lower indexing cost and supports incremental updates. HippoRAG [8] uses a knowledge graph with Personalized PageRank to retrieve across several documents in one step, drawing on models of human memory. Peng et al. [9] survey the field and group methods by how the graph is built, how it is searched and how retrieved structure is given to the generator.

**Citation networks in law.** Long before LLMs, Fowler et al. [10] treated court opinions and their citations as a network and showed that network centrality measures the legal importance of precedents in US Supreme Court cases. Legal corpora already contain an explicit graph: judgments cite statutes and earlier judgments.

**Relevance to this project.** FST judgments come with structured lists of the provisions applied and the precedents cited. This project therefore builds the graph deterministically from those fields and statute text, not by LLM entity extraction (Decision D-003). Every edge can be traced to a source, which matters more for legal citation than the broad summarization GraphRAG targets. LLM-derived edges remain a possible extension.

---

## 4. Legal AI and legal NLP

**Surveys and benchmarks.** Zhong et al. [11] survey NLP for legal systems, including judgment prediction, similar-case matching and legal question answering. LexGLUE [12] collects legal language-understanding tasks; LEGAL-BERT [13] shows that pre-training on legal text helps on such tasks. LegalBench [14] evaluates legal reasoning in LLMs across 162 tasks contributed by legal professionals, organized by types of legal reasoning.

**Legal RAG.** LegalBench-RAG [15] targets the retrieval step specifically: 6,858 query–answer pairs traced back to exact source passages over a corpus of more than 79 million characters. Its premise, that legal RAG must retrieve precise passages and not whole documents, supports paragraph-level chunking of judgments and section-level chunking of statutes here. CBR-RAG [16] combines case-based reasoning with RAG for legal question answering: past cases are retrieved through the CBR retrieve stage and used to enrich the prompt, with comparisons of general and legal embeddings and of different similarity schemes. Case-based reasoning matches how lawyers prepare: find decided cases like this one and see what worked.

**Pakistani legal NLP.** Work on Pakistani law is limited and focused mostly on statutes. LEGAL-UQA [17] is an Urdu–English question-answering dataset of 619 pairs built from the Constitution of Pakistan, and its authors note that article-wise chunking suits RAG-based legal chatbots. ULBERT [18] fine-tunes a BERT model on a bilingual constitutional dataset for semantic retrieval. On judgments, Sharafat et al. [19] annotate Lahore High Court civil judgments for entity extraction (dates, case numbers, cited cases, names). We found no published work on retrieval or reasoning over Federal Service Tribunal judgments, or on linking service-law statutes to tribunal decisions.

---

## 5. Long context, decomposition and recursive language models

**Decomposition.** Least-to-most prompting [20] solves a problem by first breaking it into simpler sub-problems and answering them in sequence. Decomposed prompting [21] gives each sub-task to a dedicated handler, which can itself be a model call or a tool. ReAct [22] interleaves reasoning steps with actions such as search, so the model can gather evidence as it reasons. MemGPT [23] manages a model's limited context like an operating system manages memory, moving information in and out of the context window.

**Context limits.** Beyond the "lost in the middle" effect [2], a technical report by Chroma [24] measured "context rot": model performance on simple tasks worsening as input length grows, even within the advertised context window. For this project the inputs are a lawyer's case papers plus many retrieved judgments, which can exceed what an 8B model handles well in one prompt.

**Recursive Language Models.** Zhang, Kraska and Khattab [25] propose Recursive Language Models (RLMs). The long input is not placed in the model's context. It is stored as a variable in a Python REPL, and the root model writes code that inspects, filters and splits it, calling the model again on selected parts through a sub-call function. The authors report handling inputs far beyond the model's context window. They also post-train a small model, RLM-Qwen3-8B, which they report improves on base Qwen3-8B by 28.3% on average and approaches vanilla GPT-5 on three long-context tasks. The weights are published (`mit-oasys/rlm-qwen3-8b-v0.1`). An 8B model fits a 6 GB consumer GPU once quantized, which makes RLM practical for this project's hardware.

**Reproduction.** Wang [26] reproduced RLMs with open models (DeepSeek v3.2, Kimi K2) on S-NIAH and OOLONG. Depth-1 recursion improved complex reasoning tasks, but performed worse than a plain model on simple retrieval, and depth-2 recursion degraded results sharply. This project therefore limits recursion to depth 1 by default and answers simple look-ups through direct retrieval.

**Relevance to this project.** RLM's sub-calls are independent model calls with their own inputs, which makes them natural units of work to send to different machines. That property is what this project builds on: the root call stays on the hub and sub-calls are queued for any available laptop.

---

## 6. Local and distributed inference

**Efficient serving.** vLLM [27] introduced PagedAttention to manage the attention key–value cache in fixed blocks, improving serving throughput. It targets data-centre GPUs. llama.cpp [28] runs quantized models on consumer hardware and can split a model between GPU and CPU memory, which is what allows an 8B model on a 6 GB GPU. The Qwen3 technical report [29] describes the base model family used here.

**Distributed inference across devices.** Petals [30] splits a large model's layers across volunteer machines over the internet so that no single machine has to hold the whole model; a follow-up [31] reports that such distributed generation can be about ten times faster than offloading the model to local memory. exo [32] pools consumer devices on a local network into one inference cluster, connected peer-to-peer and splitting the model across them.

**Relevance to this project.** Petals and exo distribute *one model's layers* across devices, which helps when the model is too large for any single device and is limited by network latency on every generated token. Here each laptop can hold the whole 8B model, so the project distributes *whole model calls* instead: RLM sub-calls are queued and each laptop runs complete calls (Decision D-001). This avoids per-token network traffic and lets a laptop join or leave between jobs without stalling the others. We found no prior work that distributes RLM sub-calls across edge devices.

---

## 7. Hallucination in legal AI

**General-purpose models.** Dahl et al. [33] measured legal hallucination in general-purpose LLMs on questions about US federal court cases and found hallucination rates from 69% to 88% for the models tested. They also found models often fail to correct a user's false legal premise and are poorly calibrated about their own errors.

**Commercial legal research tools.** Magesh et al. [34] tested commercial legal AI tools that use RAG and are marketed as reducing hallucination. They found the tools hallucinated between 17% and 33% of the time, less than general chatbots but far from free of errors. Their categories distinguish answers that are wrong from answers whose cited source does not support the claim (misgrounded).

**Relevance to this project.** RAG alone does not stop hallucination in legal answers, and a citation that exists can still fail to support the claim it is attached to. This project therefore checks both that every citation exists in the corpus and that the cited passage supports the claim (Implementation Plan, Phase 6), and measures both rates.

---

## 8. Evaluating attributed answers

ALCE [35] benchmarks LLMs on producing answers with citations and measures citation recall (whether claims are supported by their citations) and citation precision (whether each citation is needed). FActScore [36] breaks long-form output into atomic facts and scores the fraction supported by a knowledge source. RAGAS [37] offers reference-free metrics for RAG pipelines, including faithfulness to retrieved context and answer relevance. These metrics underlie the citation-support and unsupported-claim measures in the evaluation plan, adapted so that the knowledge source is the FST corpus and statute text.

---

## 9. Gap and positioning

| Area | What exists | What is missing for FST practice |
|---|---|---|
| Legal RAG | Benchmarks and systems for US, Australian and other corpora [15, 16, 34] | No system over Pakistani service-tribunal judgments |
| Pakistani legal NLP | Constitution QA and retrieval [17, 18]; entity extraction from High Court judgments [19] | No graph linking service statutes, the Constitution and tribunal decisions |
| Graph RAG | LLM-built entity graphs [6, 7, 8] | Graphs whose every edge is traceable to a legal source |
| Recursive LMs | RLM with a REPL and sub-calls [25, 26] | Sub-calls distributed across edge devices |
| Distributed inference | Layer-split across devices [30, 31, 32] | Task-level distribution for small models that fit on each device |
| Legal hallucination | Measured in chatbots and commercial tools [33, 34] | Verification built into an offline tool for a specific forum |
| Lawyer workflow | Research tools answer questions | Hearing-to-hearing follow-up: directions recorded, research prepared before the next date |

The project's contributions are therefore:

1. A knowledge graph of FST judgments, the Constitution and the service statutes, built from structured fields with traceable edges.
2. An RLM-based analysis pipeline whose sub-calls run on a queue served by any number of edge laptops, with failure recovery.
3. Citation existence and support verification built into the answer pipeline, with measured hallucination rates against a RAG baseline.
4. A hearing-follow-up layer that turns a judge's directions into prepared research before the next hearing.
5. A fully offline, multi-user deployment that keeps each lawyer's case material private.

---

## References

[1] P. Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks," *NeurIPS*, 2020. arXiv:2005.11401.

[2] N. F. Liu et al., "Lost in the Middle: How Language Models Use Long Contexts," *TACL*, 2024. arXiv:2307.03172.

[3] A. Asai, Z. Wu, Y. Wang, A. Sil, H. Hajishirzi, "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection," *ICLR*, 2024. arXiv:2310.11511.

[4] S. Dhuliawala et al., "Chain-of-Verification Reduces Hallucination in Large Language Models," 2023. arXiv:2309.11495.

[5] P. Sarthi et al., "RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval," *ICLR*, 2024. arXiv:2401.18059.

[6] D. Edge et al., "From Local to Global: A Graph RAG Approach to Query-Focused Summarization," 2024. arXiv:2404.16130.

[7] Z. Guo et al., "LightRAG: Simple and Fast Retrieval-Augmented Generation," 2024. arXiv:2410.05779.

[8] B. J. Gutiérrez et al., "HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models," *NeurIPS*, 2024. arXiv:2405.14831.

[9] B. Peng et al., "Graph Retrieval-Augmented Generation: A Survey," 2024. arXiv:2408.08921.

[10] J. H. Fowler, T. R. Johnson, J. F. Spriggs II, S. Jeon, P. J. Wahlbeck, "Network Analysis and the Law: Measuring the Legal Importance of Precedents at the U.S. Supreme Court," *Political Analysis*, 15(3), 2007.

[11] H. Zhong et al., "How Does NLP Benefit Legal System: A Summary of Legal Artificial Intelligence," *ACL*, 2020. arXiv:2004.12158.

[12] I. Chalkidis et al., "LexGLUE: A Benchmark Dataset for Legal Language Understanding in English," *ACL*, 2022. arXiv:2110.00976.

[13] I. Chalkidis et al., "LEGAL-BERT: The Muppets straight out of Law School," *Findings of EMNLP*, 2020. arXiv:2010.02559.

[14] N. Guha et al., "LegalBench: A Collaboratively Built Benchmark for Measuring Legal Reasoning in Large Language Models," *NeurIPS Datasets and Benchmarks*, 2023. arXiv:2308.11462.

[15] N. Pipitone, G. Houir Alami, "LegalBench-RAG: A Benchmark for Retrieval-Augmented Generation in the Legal Domain," 2024. arXiv:2408.10343.

[16] N. Wiratunga et al., "CBR-RAG: Case-Based Reasoning for Retrieval Augmented Generation in LLMs for Legal Question Answering," *ICCBR*, LNCS 14775, 2024. arXiv:2404.04302.

[17] (authors to confirm), "LEGAL-UQA: A Low-Resource Urdu-English Dataset for Legal Question Answering," 2024. arXiv:2410.13013.

[18] Abbas, Nawaz, Niazi, Awais, "ULBERT," *Frontiers in Big Data*, 2025. doi:10.3389/fdata.2025.1448785.

[19] Sharafat, Nasar, Jaffry, "Legal Data Mining from Civil Judgments," Springer, 2019. doi:10.1007/978-981-13-6052-7_37.

[20] D. Zhou et al., "Least-to-Most Prompting Enables Complex Reasoning in Large Language Models," *ICLR*, 2023. arXiv:2205.10625.

[21] T. Khot et al., "Decomposed Prompting: A Modular Approach for Solving Complex Tasks," *ICLR*, 2023. arXiv:2210.02406.

[22] S. Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models," *ICLR*, 2023. arXiv:2210.03629.

[23] C. Packer et al., "MemGPT: Towards LLMs as Operating Systems," 2023. arXiv:2310.08560.

[24] K. Hong, A. Troynikov, J. Huber, "Context Rot: How Increasing Input Tokens Impacts LLM Performance," Chroma technical report, 2025.

[25] A. L. Zhang, T. Kraska, O. Khattab, "Recursive Language Models," 2025. arXiv:2512.24601.

[26] D. Wang, "Think, But Don't Overthink: Reproducing Recursive Language Models," 2026. arXiv:2603.02615.

[27] W. Kwon et al., "Efficient Memory Management for Large Language Model Serving with PagedAttention," *SOSP*, 2023. arXiv:2309.06180.

[28] G. Gerganov et al., "llama.cpp," software, https://github.com/ggml-org/llama.cpp.

[29] Qwen Team, "Qwen3 Technical Report," 2025. arXiv:2505.09388.

[30] A. Borzunov et al., "Petals: Collaborative Inference and Fine-tuning of Large Models," *ACL System Demonstrations*, 2023. arXiv:2209.01188.

[31] A. Borzunov et al., "Distributed Inference and Fine-tuning of Large Language Models Over The Internet," *NeurIPS*, 2023. arXiv:2312.08361.

[32] exo labs, "exo: Run your own AI cluster at home with everyday devices," software, https://github.com/exo-explore/exo.

[33] M. Dahl, V. Magesh, M. Suzgun, D. E. Ho, "Large Legal Fictions: Profiling Legal Hallucinations in Large Language Models," *Journal of Legal Analysis*, 2024. arXiv:2401.01301.

[34] V. Magesh et al., "Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools," *Journal of Empirical Legal Studies*, 2025. arXiv:2405.20362.

[35] T. Gao, H. Yen, J. Yu, D. Chen, "Enabling Large Language Models to Generate Text with Citations," *EMNLP*, 2023. arXiv:2305.14627.

[36] S. Min et al., "FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation," *EMNLP*, 2023. arXiv:2305.14251.

[37] S. Es, J. James, L. Espinosa-Anke, S. Schockaert, "RAGAS: Automated Evaluation of Retrieval Augmented Generation," *EACL System Demonstrations*, 2024. arXiv:2309.15217.

> **Before submission:** check every reference against its source (title, authors, venue, year), and complete the shortened entries [17], [18] and [19] with full titles and author names from the publisher pages.
