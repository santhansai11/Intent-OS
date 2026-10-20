# IntentOS
## Review 2: Methodology, Implementation and Initial Results

**A permission-scoped AI workspace with durable intent execution and local hybrid retrieval**

Prepared for project review | 16 October 2026 | Implementation draft

IntentOS converts a natural-language goal into a persistent process that can search documents, prepare reports, and invoke connected services. This review extends the earlier problem and literature review with implemented modules, an execution algorithm, interface evidence, and a small reproducible retrieval experiment.

The central engineering question is whether evidence retrieval, explicit file boundaries, observable completion checks, and resumable execution can make multi-step personal workflows easier to inspect and recover. The prototype operates in userspace on Windows; it does not replace or modify the operating-system kernel.

### Implemented in this review

- Local uploads with distinct Source and Reference roles; reference-guided drafting.
- Incremental SQLite FTS5 keyword retrieval and local semantic embeddings combined through reciprocal rank fusion.
- Cited source passages, OCR for scanned pages/images, and explicit partial-coverage reporting.
- Persistent intent dependencies, bounded parallel document reads, configurable execution capacity, and memory-pressure throttling.
- Searchable and deletable history, pinned intents, light/dark themes, and separate result, workflow, source, and activity views.
- Regression tests for permissions, upload boundaries, deletion behavior, retrieval freshness, completion checks, and concurrent execution.

### Evidence at a glance

| Measurement | Observed result |
| --- | --- |
| Python regression suite | 220 tests: 219 passed, 1 optional test skipped |
| Frontend tests / production build | 5 passed / successful |
| Controlled retrieval corpus | 6 DOCX files, 19,704,013 bytes, 45 passages |
| First index / unchanged refresh | 83.942 seconds / 0.025 seconds |
| Relevant document ranked first | BM25: 11/12; hybrid: 12/12 |

These are prototype observations, not general accuracy, throughput, patentability, or real-time guarantees. The retrieval queries were authored for this small corpus and were not held out.

<!-- page -->
# 1. Finalized system architecture

The application separates user interaction, decision making, authorization, execution, and evidence storage. React communicates with a loopback HTTP API and receives server-sent status updates. The runtime keeps process state and committed tool results in SQLite. Gemini or local Ollama proposes one next action; the runtime validates it before execution.

:::architecture

**Figure 1. Implemented module boundaries.** Local evidence retrieval and embedding inference run on the laptop. When Gemini is selected, the goal and needed excerpts are sent to Gemini for planning and drafting. Google integrations communicate with their respective APIs after connection setup.

### State and trust boundaries

- A process records its goal, priority, deadline, read grants, selected search roots, output folder, attachments, prerequisites, pending action, checkpoints, and answer.
- Uploads are copies in a private runtime directory. Attaching a file grants that intent access to that exact upload, not to every uploaded file.
- Retrieval filters authorized paths and excludes changed/deleted documents before ranking passages. The local index is application data, not an encrypted multi-user database.
- File contents and retrieved passages are treated as evidence. They cannot create permissions or authorize external actions.
- Pending writes and uncertain external outcomes retain explicit review states. A checkpoint confirms a recorded result; it does not make every remote API exactly-once.

### Working principle

The model proposes; the runtime authorizes, schedules, executes, and records. The user sees the result first and can open source evidence or execution details when needed. Durable state allows recovery without repeating already committed work.

<!-- page -->
# 2. Detailed methodology

### Intent admission and interpretation

The composer accepts a goal, optional attachments, selected source folders, output preferences, priority, and prerequisites. A Source attachment supplies factual material. A Reference attachment supplies headings and structural style. The planner is instructed to read references before drafting, preserve their order, and identify missing evidence rather than inventing results. This is structure-guided drafting, not pixel-perfect template reproduction.

### Evidence acquisition

Focused file search first applies folder and date constraints and excludes common tool and nested project folders by default. Comprehensive assessment summaries use folder inventory and complete reads. Question answering can use the local index: BM25 retrieves lexical matches, a local embedding model retrieves semantic matches, and reciprocal rank fusion combines their ranks [1-4].

### Scheduling and execution

The scheduler uses priority and fair checkpoint rotation, with existing deadline/aging behavior. A dependent intent becomes eligible only after all prerequisites complete. Configurable planning and file-read limits operate within a total dispatch limit. Independent reads can run concurrently; file writes exclude readers. A read-many batch reserves the read lane so nested pools cannot multiply the configured capacity.

### Validation and recovery

Observable checks verify required attachment coverage, requested nonempty line counts, listed assessment coverage, and the use of known citation markers. A rejected plan returns feedback for correction before a relevant final action. These checks do not establish semantic truth or guarantee that every claim is supported. Transient failures preserve checkpoints and retry within a bounded policy; persistent failures become visible for recovery.

# 3. Algorithm and flowchart

:::flow

**Figure 2. Input to output flow.** At each checkpoint the process releases its resource and returns to the scheduler. Completion requires both a useful answer or committed output and the applicable observable checks.

<!-- page -->
# 4. Module-wise implementation

| Module | Implemented responsibility and evidence |
| --- | --- |
| Composer and workbench | Attach up to 12 files, assign roles, choose scopes and prerequisites, view concise outcomes. React components and browser smoke tests. |
| Upload store | Stream authenticated uploads, restrict file types, enforce 100 MB limit, maintain metadata and per-intent access. Upload lifecycle and HTTP tests. |
| Runtime and scheduler | SQLite process state, durable checkpoints, resource locks, priority changes, dependency eligibility, bounded slots and memory throttling. Scheduler and recovery tests. |
| Document extraction | Read text and office documents; paginate DOCX text without unpacking embedded media. Local OCR for uploaded images and selected PDF pages. |
| Knowledge index | Persistent indexing queue, metadata cache, FTS5 passages, local vectors, stale-file exclusion and scoped rank fusion. Retrieval and isolation tests. |
| Planner and context | Gemini/Ollama structured next actions, retained source evidence, reference instructions, bounded context and omission notices. Live draft smoke test. |
| Completion checks | Contiguous attachment reads, all listed assessments, minimum line counts and known citation markers. Negative and positive regression tests. |
| History and evidence UI | Search, pin, individual/bulk deletion, actual execution graph, source passages and audit details. Test-only deletion preserves originals. |
| Connected capabilities | Existing Gmail, Drive, Calendar and Maps tools remain available through the capability boundary. This upgrade did not send test email. |

### Interaction between modules

A reference-based draft demonstrates the interaction: two uploads become explicit process inputs; the planner chooses a parallel read; the runtime validates both paths; each returned document retains provenance; the next model call sees both sources; completion checks require their coverage; the UI presents the formatted draft and the two read branches.

This composition is the project’s implementation focus. Durable execution and RAG already exist in established systems [1, 5, 6]. A claim that this is a new invention requires a separate, systematic prior-art assessment. No such claim is established by this prototype.

<!-- page -->
# 5. Technologies and tools used

| Layer | Technology used in this implementation |
| --- | --- |
| Runtime | Python 3.14.6 on Windows 11, threading and bounded thread pools |
| Persistence | SQLite transactions, WAL mode, FTS5 full-text search |
| Interface | React 18, Vite 5, CSS variables, responsive layouts, server-sent events |
| AI planning | Configured Gemini provider; optional local Ollama planner |
| Local embeddings | Ollama API with nomic-embed-text; task-specific query/document prefixes |
| Extraction and OCR | Python document readers, bounded XML extraction, PyMuPDF 1.28.2, local English Tesseract data |
| Integrations | Google OAuth and Gmail/Drive/Calendar/Maps APIs through existing adapters |
| Verification | Python unittest, Node test runner, production build, live browser inspection |

# 6. Dataset description

The controlled retrieval experiment uses six user-provided Computer Networks Lab DOCX assessments. PDF versions in the same folder were excluded from this benchmark to avoid giving duplicate representations an advantage. The benchmark corpus totals 19,704,013 bytes and produces 45 text passages. The live knowledge index may contain additional files from later folder refreshes; those files are outside this controlled measurement.

| Assessment | Content represented in the document |
| --- | --- |
| 1 | Hub and switch LAN simulations and communication observations |
| 2 | Interconnecting two LANs using switches and a router |
| 3 | Star, ring, bus, tree, mesh and hybrid topologies |
| 5 | ARQ protocols, acknowledgement loss and retransmission simulations |
| 6 | UDP/TCP socket programming and client/server examples |
| 7 | IPv4 addressing, masks and address calculations |

Assessment 4 was not present among these six source files. Embedded screenshots were not interpreted for this text-retrieval experiment. Descriptions and code in student documents are evidence of reported work, not independently executed or verified networking experiments.

The reference-draft smoke test uses two clearly labeled synthetic files: one section outline and one short factual source. It tests document roles and heading order without relying on private account operations.

<!-- page -->
# 7. Data preprocessing

The index resolves each path through the capability boundary before extraction. DOCX extraction reads paragraph/table text, headers, footers and notes while leaving embedded media compressed. It rejects oversized text XML and unsupported declarations. PDF indexing preserves page markers and can use installed local OCR for pages without extractable text. Empty or unreadable material is reported.

Text is split into passages of up to 1,400 characters with approximately 180 characters of overlap, preferring a nearby newline. Each passage records its path, ordinal, offset, content and coverage note. Citation identifiers derive from the path, file stamp and passage ordinal. They are stable for the same indexed version and change after a file refresh.

Modification time and size detect unchanged files; content digests are also stored. On refresh, changed documents replace their old passages atomically. Queries exclude stale and deleted documents even before refresh. The current application does not continuously watch the filesystem.

Local vectors are computed in batches of 16. For the Nomic model, documents use the search_document prefix and queries use search_query, as specified by its model card [4]. Cloud-backed model aliases are rejected before transmitting document text to the embedding endpoint.

For each retrieval list, rank fusion adds 1 / (60 + rank). Up to 80 lexical candidates and 80 semantic candidates contribute. The response contains at most eight passages, with at most three passages from one file. These scores are ranking values, not calibrated confidence probabilities.

# 8. Experimental setup

Measurements were taken on one Windows 11 laptop with 7.8 GiB reported RAM, eight logical CPUs, Python 3.14.6, and local Ollama. The cold index pass had zero cache hits. A second immediate pass measured unchanged-file refresh. Twelve developer-authored queries, two per assessment, were then run in BM25 and hybrid modes against the same six-document corpus.

**Metrics:** Hit@1 is the fraction of queries whose expected document is first. MRR@5 averages the reciprocal rank of the first relevant unique document within the first five returned documents, assigning zero if absent. Latency is measured by the retrieval implementation; reported values are medians of one run per query.

**Reproduction:** Run scripts/rag_evaluation.py with the corpus folder, a fresh --data-root, and an --output JSON path. Raw query text, expected documents, returned filenames, ranks, warnings, and timings are recorded in rag-results.json. Using an existing data root changes cold-cache conditions.

<!-- page -->
# 9. Initial implementation screenshots

### Workspace and attachment roles

The workspace capture is kept on the local machine only. It shows recent goals that include email addresses, so it is not published in this repository.

**Figure 3. Live interface with two uploaded files.** The reference supplies report headings; the source supplies facts. Advanced folder, output and scheduling controls remain under Options to keep the default composer concise.

The screen was captured from the running application during the synthetic drafting test. It is implementation evidence, not a design mockup. Existing user history remains visible in the sidebar; the upgrade preserves those records.

### Visual design decisions

The layout uses a dark green navigation rail, restrained teal accents, light cards, and a matching dark theme. Results use readable headings and lists. Diagnostics move to Activity and an optional runtime inspector; source evidence remains one tab away. Responsive layouts collapse navigation on narrow screens, and reduced-motion preferences are respected.

<!-- page -->
# 9. Initial implementation screenshots (continued)

### Actual execution graph

The workflow capture is kept on the local machine only, for the same reason: the sidebar lists goals that contain email addresses.

**Figure 4. A recorded files_read_many checkpoint.** Both uploaded documents appear as branches of one parallel read action. The graph is built from actual completed steps and a pending action; it is not a prediction of an unexecuted plan.

### Observed draft behavior

The live Gemini test read both files and returned a brief with Objective, Implementation, Validation and Next Steps in the reference order. The completion strip showed 2/2 required attachments read. The generated text retained the source’s limitation that broad retrieval quality had not been evaluated. This is one successful template-following example, not a measured template-conformance rate.

The workflow UI supports dependencies between intents. It does not yet support editing arbitrary graph nodes or scheduling an entire model-generated DAG in advance. Within an intent, independent document reads can be parallelized; other decisions remain cooperative checkpoints.

<!-- page -->
# 9. Initial implementation screenshots (continued)

### Knowledge retrieval and source evidence

The knowledge-search capture is kept on the local machine only. It shows a local folder path and identifying text from a source document.

**Figure 5. Search restricted to the selected Computer Networks Lab folder.** The interface shows the active retrieval method, latency, exact source markers, filenames and excerpts. Coverage details disclose extraction limits. Live index counts can exceed the six-document benchmark after further folder indexing.

### Evidence versus completion

Retrieving a passage does not prove that a whole file has been read. For a question, selected passages may be sufficient. For a summary of every assessment, the planner must inventory and read the required documents; truncated reads need continuation. This distinction is enforced where coverage can be observed and disclosed elsewhere.

<!-- page -->
# 10. Preliminary results

| Retrieval measure | BM25 | Hybrid BM25 + local vectors |
| --- | --- | --- |
| Expected document ranked first | 11 of 12 | 12 of 12 |
| Hit@1 | 91.7% | 100.0% |
| MRR@5 | 0.944 | 1.000 |
| Median query latency | 12 ms | 276 ms |

The first index pass took 83.942 seconds, including local embedding computation. An unchanged refresh took 0.025 seconds and reused all six documents. This demonstrates cache reuse on the measured corpus; it does not establish performance across 100,000 files.

In this small test, hybrid retrieval improved one query’s top-ranked document at a median latency cost of 264 ms. No repeated-run confidence interval, held-out evaluation or broad corpus comparison was performed. The result supports continuing the experiment, not a universal superiority claim.

### Functional verification

- Python suite: 220 tests run, 219 passed, one optional symlink-related test skipped on this host.
- Frontend suite: five folder-selection regressions passed; production build succeeded.
- Workbench regressions: 20 tests cover upload isolation and bounds, authenticated HTTP lifecycle, shared-copy deletion, dependency gating, concurrency limits, stale-file filtering, local vector fusion and completion contracts.
- Browser inspection: upload roles, formatted draft, execution graph, knowledge search, history controls and responsive light/dark views checked on the running application.
- Local OCR successfully extracted text from the supplied review checklist image. Recognition accuracy was not benchmarked against a manually transcribed corpus.
- A live Gemini RAG answer completed with known source citations after recovery from temporary HTTP 503 errors. Grouped citation syntax discovered during testing is now validated marker by marker. This demonstrates one completed answer and checkpoint recovery, not general factual accuracy.

### Interpretation limits

Tests of remote service responses use mocks unless explicitly described as live tests. A successful suite does not guarantee continuous Google/Gemini availability or correct generated prose. Completion checks can detect missing known citations and incomplete reads; they cannot establish that every cited passage entails every claim.

<!-- page -->
# 11. Problems encountered and solutions

| Problem | Implemented response and remaining limitation |
| --- | --- |
| Broad scans ignored user intent | Focused folder/date filtering, exclusions, selected-path handling and a reusable local index. Large-drive performance still needs measurement. |
| Large DOCX blocked assessment summaries | Bounded text-only XML extraction supports DOCX up to 100 MB and paginated content. Embedded images remain outside ordinary DOCX text coverage. |
| Uploaded references were not explicit inputs | Source/Reference roles, retained context and required-read checks. Structural fidelity is model-guided rather than exact layout copying. |
| Partial reads looked complete | Contiguous chunk/page coverage checks prevent a final chunk from standing in for the whole source. Unsupported formats disclose partial coverage. |
| Source-free or invented citations | Known-marker validation requests a correction. Semantic entailment remains unverified. |
| Unbounded parallelism could exhaust memory | Separate total/planning/read limits, read-batch reservation and dispatch throttling at 90% memory use. Running calls are not preempted. |
| History cleanup risked originals | Terminal-intent-only deletion, dependency checks and optional unshared upload-copy cleanup. Originals and generated artifacts are preserved. |
| Temporary model service errors | Checkpoints and bounded retries retain progress; blocked tasks can resume. Provider availability cannot be guaranteed locally. |

### Candidate contribution to evaluate

The project combines permission-scoped local retrieval, durable goal execution, source coverage checks, and user-visible recovery in one personal workspace. The useful research question is whether this composition reduces repeated work and completion mistakes compared with a conversational baseline. RAG, rank fusion and checkpointing are established techniques [1-6]; the current evidence does not establish patent novelty.

### Next experimental phase

Use a larger held-out corpus with paraphrased, ambiguous, no-answer, date-filtered and permission-boundary queries. Measure retrieval recall, citation support, task completion, duplicate side effects under injected failures, peak memory, index size and user correction effort. For larger indexes, evaluate an approximate-nearest-neighbour backend and a controlled file-change watcher. Add retrieval reranking only after demonstrating benefit over the current baseline.

<!-- page -->
# 12. Updated references

1. Lewis, P., et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS, 2020. https://arxiv.org/abs/2005.11401

2. Cormack, G. V., Clarke, C. L. A., and Buettcher, S. Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods. SIGIR, 2009. https://cormack.uwaterloo.ca/cormack/cormacksigir09-rrf.pdf

3. SQLite. FTS5 Extension documentation, including BM25 ranking. https://sqlite.org/fts5.html

4. Nomic AI. nomic-embed-text-v1.5 model card and task instruction prefixes. https://huggingface.co/nomic-ai/nomic-embed-text-v1.5

5. Temporal. Workflow documentation. https://docs.temporal.io/workflows

6. LangChain. LangGraph persistence documentation. https://docs.langchain.com/oss/python/langgraph/persistence

7. Ollama. Generate embeddings API. https://docs.ollama.com/api/embed

8. PyMuPDF. OCR recipes and page API. https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html

9. Tesseract OCR. Official fast language data. https://github.com/tesseract-ocr/tessdata_fast

10. IntentOS project. Review 1: Problem, Literature and Proposed Idea. Earlier project draft supplied in this repository. This review continues its userspace process model while separating proposed capabilities from verified implementation.

Web references checked during implementation on 16 October 2026. Earlier foundational operating-systems references remain in Review 1; this list adds sources directly relevant to the implemented retrieval and execution design.

### Submission checklist

This draft includes finalized architecture, methodology, an input-to-output algorithm, module implementation, tools, dataset, preprocessing, experimental setup, real screenshots, preliminary results, problems and solutions, and updated references. It also explains working principles and module interactions requested by the supplied Review 2 checklist.

Before formal submission, add institution-specific cover information and supervisor details if required, verify the described dataset can be shared with reviewers, and rerun the evaluation after any code or model changes. Expand the experimental section before making broader research claims.
