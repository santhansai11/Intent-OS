# IntentOS

**Give your goal a place to run.**

IntentOS is an AI workspace backed by a durable userspace kernel. Describe a goal; Gemini or local Ollama chooses capabilities, observes real results, and advances the task. The kernel schedules decisions, checks per-goal permissions, arbitrates resources, and checkpoints progress to SQLite. A direct collection workflow searches and copies related files without calling a model.

The application has no canned meeting results, simulated routes, or pretend email delivery. File operations execute locally. Gemini receives goals and needed document excerpts; Ollama keeps inference local. Providers never switch automatically. See [the detailed working model](docs/WORKING_MODEL.md) for architecture, search coverage, recovery semantics, and measured latency.

## Workbench upgrade (Review 2)

The workspace now includes multi-file uploads with **Source** and **Reference** roles, reference-guided drafting, searchable/pinnable intent history, individual/bulk history deletion, light/dark themes, and Result/Workflow/Sources/Activity views. Uploads are local copies, scoped to the intents that explicitly attach them. History deletion preserves originals and generated outputs; removing attached copies is an explicit option and shared copies remain until no intent uses them.

The **Knowledge** page builds an incremental local index and searches it using SQLite FTS5/BM25. For hybrid retrieval install a local embedding model with `ollama pull nomic-embed-text`, enter `nomic-embed-text` in Retrieval settings, and refresh the selected folder. Embeddings use the loopback Ollama API; remote model aliases are rejected. Gemini still receives the goal and needed excerpts when Gemini is the chosen planner. No automatic provider fallback occurs.

The **Process studio** supports 1-8 total execution slots, separate planning/read limits, priority changes, and prerequisite intents. Memory use at or above 90% limits new dispatch to one slot when adaptive mode is enabled. These are cooperative userspace execution limits, not Windows process priorities or hard real-time guarantees. A prerequisite must complete successfully; failed/cancelled prerequisites leave dependents waiting for user action.

Local OCR uses PyMuPDF/Tesseract. Place English data from the official [tessdata_fast repository](https://github.com/tesseract-ocr/tessdata_fast) at `storage/runtime/ocr/eng.traineddata`. It is already installed on this development laptop. Uploaded images and `files_ocr` use local OCR; embedded DOCX images are not automatically OCRed.

Limits are explicit: 12 uploads per intent, 100 MB per upload, 25,000 queued entries per index job, 2,000 chunks per document, and 300 pages for PDF indexing. Some document readers return bounded excerpts; comprehensive summaries must follow pagination or disclose partial coverage. Index refresh is manual or requested by an intent; changed/deleted files are excluded from search until refreshed. Dense similarity currently scans the permitted vectors, so 100,000-file retrieval performance is not established.

Observable completion checks enforce required attachment coverage, requested line counts, known RAG citation markers, and discovered assessment coverage. They do not prove that every generated claim is true or that every reference style detail was followed. The Review 2 draft and benchmark data are in `docs/review2/`; reproduce the 12-query experiment with:

```powershell
python scripts/rag_evaluation.py --corpus "D:\nani\semester\Computer Networks\Lab" --data-root storage_test/rag-evaluation/runtime --output storage_test/rag-evaluation/results.json
```

Additional API routes: `POST /api/uploads` (authenticated binary body, URL-encoded `X-Filename`), `POST /api/uploads/remove`, `POST /api/history/delete`, `GET /api/knowledge`, and `POST /api/knowledge/search`. Intent submission also accepts `attachments` and `depends_on`; intent controls include `pin` and `priority`.

## Installation

Requires Python **3.10+** and Node **18+** to build the interface. For natural-language planning choose a Gemini API key or [Ollama](https://ollama.com/download). Direct topic-file gathering requires neither.

```powershell
python -m pip install -r requirements.txt
npm --prefix frontend install
npm --prefix frontend run build
python run_intentos.py --app
```

Open **http://127.0.0.1:8765**. The Python server serves the built React app; you do not need a separate frontend process after building it. `--server` starts without opening a browser. Running `python run_intentos.py` also starts the server.

1. In **Connections**, choose **Gemini** for cloud planning or **Ollama** for private local planning.
2. For Gemini, save your key in the OS credential store, refresh available models, and select a text model. The default is `gemini-3.5-flash-lite`. For Ollama, select a downloaded local model such as your existing `qwen3:4b`.
3. Add source folders under **Accessible folders** and save provider and folder settings.
4. In Overview, choose **Ask anything** or **Gather related files · no AI needed**. For direct gathering, enter topics such as `cloud computing`, optionally with a date: `AWS files saved after September 1 2026`. Put the destination in the output controls.
5. Choose **Selected folders** (expand **Choose folders** to select sources; configured source folders are selected by default), or **Entire computer · accessible files** for that goal. The workspace remains available for outputs; that does not add it to explicitly selected search folders.
6. Set **Save in folder** to an absolute folder such as `D:\meeting` or `C:\Users\you\Desktop\Reports`. It may already exist; missing folders are created when a file is saved. This is a separate per-goal grant, so you do not need whole-computer access or to add the output folder to Connections. Optionally enter a new collection folder name or output filename. Leave Save in folder blank to use the workspace. Both AI providers receive the selected destination, and relative output filenames resolve there.
7. The visible output checkbox grants creation of new collections/reports for this goal. Disable it to review those actions individually. Moves, overwrites and calendar changes still require exact-action approval. An explicit send-email request with one recipient and message context authorizes one generated email without another confirmation.

Gemini keys never appear in source code, settings JSON, task context, or browser responses. The password field stays empty after saving. A `GEMINI_API_KEY` environment variable is also supported as a fallback; the key saved in Connections takes precedence. Saving a key activates Gemini for new goals. Use **Test & use model** to verify a real response and save your chosen model. Google account OAuth is separate and unnecessary for local files or Gemini. Free-tier availability and quotas belong to the Google project; IntentOS does not enable billing or silently change providers when a quota is reached. [Gemini model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) · [Pricing and free-tier details](https://ai.google.dev/gemini-api/docs/pricing).

### Files and summary formats

File gathering scans filenames and cached document text, copies matches into a **new** folder, and creates a provenance manifest plus downloadable ZIP. Original files are never moved or edited. Duplicate filenames receive stable suffixes. Search matches whole topic phrases: `operating system` does not match `system` alone. Separate alternatives with commas, for example `operating system, OS`. Direct-mode destination instructions are rejected with guidance to use the separate folder field or Ask anything. This remains lexical matching, so an incidental mention can still match; it is not semantic classification.

Summary exports create real **PDF, DOCX, PPTX, XLSX, TXT, Markdown, HTML, CSV, JSON, RTF, ODT, EPUB, and ZIP** files. Office formats use their actual document containers, not renamed text. These are prose summaries: PPTX paginates content into slides, XLSX/CSV organize sections into rows, and ZIP contains Markdown. Unsupported extensions are rejected explicitly. Scanned-document OCR and arbitrary file-format conversion are not implemented.

Whole-computer access means files readable by your existing OS account, with credential, hidden, kernel-state and OS-managed-directory exclusions. It does not elevate permissions. **Search in** shows the actual source folders; the output folder does not add search locations. Scans first discover filenames across those sources, then inspect cached document text. Last-modified date filters run before document extraction. “After September 1 2026” starts September 2; “since” includes September 1. Nested code projects (identified by Git/build manifests) and dependency/build/tool directories are skipped; explicitly selected project roots are searched, and direct mode offers **Include nested code projects**. A durable SQLite queue yields to the scheduler every 250 items or about two seconds, and automatically continues until finished. There is no overall 20-second, 50,000-entry or 1,000-match cutoff. Live counts distinguish discovered files from contents checked. Pause/restart preserves progress; copying starts only after the scan finishes. Content search still examines the first 16,000 extracted characters of supported documents up to 10 MB, with no OCR. Prior IntentOS collection folders are excluded to avoid gathering copies repeatedly. Use focused source folders for faster searches. Copies are limited to 500 MB per collection.

The Ollama integration uses its native [chat endpoint](https://docs.ollama.com/api/chat) and [JSON-schema structured output](https://docs.ollama.com/capabilities/structured-outputs), preserving the model's default reasoning mode. Small prompts use an 8K context; longer histories use 16K. A local decision can take minutes on limited hardware, so the request timeout is ten minutes. There is no cloud fallback and no model download triggered by the app. `OLLAMA_HOST` must be loopback. The planner checks model metadata before sending context and rejects cloud-backed models and aliases. Local model quality determines how well a complex goal is planned; unsupported capabilities are not invented.

Examples to try:

- “Find the latest document in my workspace and summarize the action items.”
- “Gather my cloud computing files into a separate meeting folder. Keep the originals unchanged.”
- “Prepare a meeting pack from my project files, then save a summary of those documents as a DOCX.”
- “Explain deadlock prevention and save a PDF in my workspace.”
- “Research how operating systems prevent deadlocks and save a brief with sources.”
- “List my calendar events tomorrow and help me prepare for the first meeting.”
- “Create a meeting at 4 PM tomorrow titled Project review.”
- “Calculate a walking route from [starting address] to [destination].”
- “Write an email to [full email address] with the meeting notes, then ask me to approve sending it.”

For development, run `python run_intentos.py --server` and `npm --prefix frontend run dev`. Vite proxies `/api` to port 8765.

## Connect Google

See [the complete setup guide](docs/GOOGLE_SETUP.md) for a new Google Cloud project, OAuth, Maps billing/key setup, supported operations and limits.

Copy `.env.example` to `.env` and fill in your own credentials. The file is ignored by Git. Restart the Python server after changing environment settings.

1. Create a Google Cloud project and configure its OAuth consent screen. For a personal project in Testing mode, add your Google account as a test user.
2. Enable **Google Calendar API**, **Google Drive API**, and/or **Gmail API**, according to the capabilities you want.
3. Create an OAuth client of type **Web application**.
4. Add this exact authorized redirect URI: `http://127.0.0.1:8765/api/google/callback`. Match the hostname and port in `GOOGLE_REDIRECT_URI` if you change them.
5. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`.
6. In **Connections**, select the services you want and click **Connect selected services**. Complete consent in Google.

The implementation uses [Google’s authorization-code flow](https://developers.google.com/identity/protocols/oauth2/web-server), a random expiring one-use state, PKCE, offline refresh, and scope checks. Tokens are stored through `keyring` in the OS credential store, never in task context, browser storage, or the SQLite process database. On Linux, an unlocked Secret Service/keyring backend is required; Windows uses Credential Manager. There is no plaintext token fallback.

| Connection | OAuth scope | Available operations |
| --- | --- | --- |
| Calendar | `calendar.events` | List with pagination; create, update and delete events after approval |
| Drive | `drive.readonly`, `drive.file` | Search, read text, download/export, upload new files |
| Gmail | `gmail.readonly`, `gmail.compose`, `gmail.send` | Search, read messages, create drafts and send plain text mail |

Drive downloads/exports and Gmail inbox reading are supported. Downloads are capped at 10 MB, uploads at 5 MB; existing files are preserved. Gmail attachments are listed but not downloaded. Reconnect existing accounts to approve the expanded scopes. Disconnect removes this app’s locally stored credentials. Revoke the grant in your Google account if you also want to remove Google-side access. Google may expire testing-mode or revoked refresh tokens; reconnect when requested.

**Maps is separate:** enable the **Routes API** and **Places API (New)**, configure Google Cloud billing, and set `GOOGLE_MAPS_API_KEY`. The real route tool calls [Compute Routes](https://developers.google.com/maps/documentation/routes/compute_route_directions). OAuth sign-in alone does not enable Maps or pay API charges. Restrict the key to these APIs and appropriate server restrictions. Place search and details are supported in addition to routing.

## OS concepts that actually execute

This is an **agent runtime organized around OS concepts**, not a replacement OS or a claim that ordinary agents cannot persist state. Its process-management layer runs above the host operating system on Windows and Linux.

| OS concept | Implementation |
| --- | --- |
| Process control block | Each intent has a UUID, goal, lifecycle state, priority, absolute deadline, folder grants, read grants, pending action, results, retry counters, and execution budget. |
| Cooperative scheduling | One quantum is one model decision or capability call. The next dispatch uses aging after 30 seconds, then near-deadline EDF, then priority with round robin among peers. |
| Bounded execution | Three worker slots; one planner call at a time; at most 48 model decisions per goal. File scans, reads, responses, prompts, and writes have bounds. Direct collection bypasses planning. |
| Resource arbitration | Exclusive named resources: local model, filesystem, Calendar, Gmail, etc. Each quantum acquires one resource, so there is no hold-and-wait lock cycle. |
| Capability security | A fixed registry validates every tool and argument. Reads need a per-goal scope or a one-action approval. New collections/reports may use the explicit per-goal output grant; other writes/sends require approval of immutable action IDs and arguments. |
| Address-space analogy | Folder grants constrain file operations to canonical paths. Hidden paths, credential files and private kernel state are excluded. These are application boundaries, not OS memory isolation. |
| Journaling/checkpoints | SQLite WAL with FULL synchronization. The process checkpoint and audit event commit together after every decision and completed call. |
| Crash recovery | Restore queued processes on startup. Completed steps are never automatically replayed. Interrupted reads can retry; interrupted writes enter REVIEW. |
| Interrupts/control | Pause and cancel are cooperative: an in-flight call finishes and its effect is recorded before the state changes. A cancellation cannot undo an already-sent email. |
| IPC/service registry | Validated capability calls dispatch to local file services and authenticated HTTP APIs. The planner does not receive a shell. |
| Observability | Server-sent events update the UI, including the actual queue, scheduler decision, resource owners, checkpoints, and audit trail. |

```text
Goal → READY → model decision → capability / question / answer
                   │
                   ├─ requires permission → APPROVAL → explicit approve / deny
                   ├─ missing detail      → WAITING_INPUT → user reply
                   └─ allowed call        → RUNNING → durable checkpoint → READY

Transient read error → RECOVERY (backoff) → READY
Setup / repeated error → BLOCKED → user fixes configuration → resume
Uncertain write outcome → REVIEW → user checks destination → retry or skip
Answer → COMPLETED
Pause → PAUSED; cancel → CANCELLED, both at a safe boundary
```

**Delivery semantics:** SQLite cannot transact atomically with Gmail or your filesystem. IntentOS does not claim exactly-once external effects. If the service times out after a write, or the process dies between a write and its checkpoint, the user must inspect the destination before retrying. Calendar creation also uses a stable operation-derived event ID. File writes use atomic replacement; file copy/move may need reconciliation after interruption.

**Scheduling semantics:** this is cooperative, not real-time preemptive scheduling. An active model call or HTTP request can delay an urgent goal using the same resource. Deadlines are best effort. CPU/RAM readings come from the host monitor, but the runtime does not enforce cgroups, OS process quotas, containers, or a security sandbox against hostile local software. Folder checks are not a substitute for OS isolation against concurrent filesystem tampering.

## Capabilities

The registry exposes real tools for: system status; file list/search/read/write/copy/move; topic search and collection; document export; PDF text replacement and merging; knowledge search, Wikipedia extracts, and multi-source research; Calendar list/create/update/delete; Drive search/read/download/upload; Gmail search/read/draft/send; Maps places/details/routes.

PDF/Office reading extracts existing text (no OCR). Document export creates the 13 formats described above. PDF editing tools save new copies and refuse to overwrite inputs or existing outputs. Text replacement supports exact, single-line ASCII text in a single horizontal style span; it uses standard fonts and may shrink text to fit. Scanned, rotated, signed, encrypted, and form PDFs need specialized editors for text changes. Merging preserves page order and interactive form fields, with separate field namespaces per input. Inputs are limited to 20 MB / 200 pages each; merges to 500 pages / 100 MB total. Free research connectors query Wikipedia, Crossref and Open Library concurrently and return excerpts/metadata with source URLs and provider failures. This is limited research, not arbitrary browser automation or full-text access to every source. Dates, recipients, destinations, and content come from the user/model and actual observations, not fixed goal templates.

To add a tool, register its schema, read scope, side-effect flag, handler, and resource identity in `services/capabilities.py`. The planner receives the registry automatically; no classifier retraining or goal-specific plan template is needed. Keep credentials outside the tool catalog and observations.

## Storage and API

- `storage/runtime/kernel.sqlite3`: private intent state and audit events; ignored by Git.
- `storage/runtime/settings.json`: selected provider, models and configured folders; no API keys.
- `storage/runtime/search-cache.sqlite3`: local document extraction cache, keyed by canonical path, modification time and size.
- `storage/runtime/kernel.lock`: host-level single-instance lock.
- `storage/workspace/`: user-visible artifacts (preserved across restarts).
- OS credential store: Gemini key and Google tokens, namespaced by the runtime directory.

`INTENTOS_DATA_DIR` can select a separate runtime directory. IntentOS is a **single-user loopback application**. It rejects untrusted Host/Origin headers and requires a per-server session token on mutations. There is no multi-user authentication; do not expose it on a public interface. Local software running as your OS account can access the app and its files. Task history is stored locally without application-level encryption; protect your OS account and backups accordingly.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/status`, `/api/events` | Snapshot and live SSE stream |
| GET | `/api/models?provider=gemini`, `/api/models?provider=ollama`, `/api/system` | Provider model discovery and host metrics |
| GET | `/api/session` | Session token for `X-IntentOS-Token` on JSON POST requests |
| POST | `/api/intents` | Goal, priority, deadline, roots, search_roots, output_folder, scopes, access_mode, auto_outputs, optional direct workflow |
| POST | `/api/intents/{id}/{action}` | approve, deny, reply, pause, resume, cancel, retry, skip |
| POST | `/api/settings`, `/api/ai/key` | Provider/models/folders; securely store or remove Gemini key |
| POST | `/api/google/connect`, `/api/google/disconnect` | Google connection lifecycle |
| GET | `/api/artifact?intent={id}&step={id}` | Download a checkpointed artifact |

## Verification and project layout

```powershell
python -m unittest discover -s tests
npm --prefix frontend test
npm --prefix frontend run build
```

Runtime regressions cover real file writes/downloads, approvals, denial, folder escapes, schema validation, fairness, EDF, aging, cancellation, resource contention, restart recovery, OAuth state/PKCE/refresh, and API CSRF/Host checks. Model decisions and Google HTTP responses are test doubles in these tests; a passing suite does not establish live model quality or access to your Google account. The symlink test skips when the host cannot create symlinks.

`tests/test_collections_exports.py` additionally reopens all 13 export formats and verifies topic matching, caching, source hashes, duplicate filenames, new-destination enforcement, search-folder isolation, direct execution without AI, narrow output grants, provider pinning, and key redaction. Run `python scripts/workflow_live_test.py` for an opt-in Gemini test using synthetic files through the real HTTP API, or add `--combined-only` for the gathering-plus-brief workflow. These scripts preserve existing configured folders and leave Gemini selected. Their verification reports stay under ignored `storage_test/`.

Measured on this machine on 9 October 2026: direct collection **0.378 s**, Gemini collection **26.849 s** (includes retry after HTTP 503), PDF summary **12.755 s**, and a combined meeting pack plus source-based Markdown brief **28.135 s**. These are small-fixture measurements, not whole-disk speed guarantees. See the working model for the test records.

For a live PDF workflow, start the server, install `qwen3:4b` in Ollama, then run `python scripts/pdf_live_test.py`. This explicit test selects that model, grants a newly created synthetic fixture folder, and submits a natural-language request through the API. It approves only the two exact expected PDF actions, saves outputs in a separate `results` folder, checks page content/order, and compares the entire originals folder's SHA-256 manifest. Each run writes a `verification.json` report under `output/pdf/`. Normal app writes still require user approval. `tests/test_pdf_tools.py` also exercises overwrite prevention, path grants, form preservation, and failure behavior.

```text
intent_kernel/runtime.py     Durable process manager, scheduler, workers, audit and recovery
intent_kernel/config.py      Local settings and environment loading
planner/agent.py             Ollama structured next-action planner
planner/router.py            Per-intent provider routing and compact Gemini context
services/capabilities.py     Validated real tool registry and file boundaries
services/collections.py      Cached topic search, source-preserving copies and manifests
services/documents.py        Thirteen real summary export formats
services/gemini.py           Bounded Gemini transport and secure API-key storage
services/connections.py      Bounded HTTP, Google OAuth and OS credential storage
api/server.py               Loopback HTTP/SSE API and React static serving
frontend/src/              Responsive task workspace, approvals and kernel inspector
tests/test_runtime.py       New runtime and integration regressions
```

The original classifier, template planner, simulated services, and classical scheduler comparison remain solely for **educational demonstrations and regression tests**. `--demo` explicitly labels synthetic results; `--compare` compares FCFS/Priority/RR/EDF on a synthetic workload. Neither powers the application. Existing documents/artifacts are preserved; the obsolete duplicate embedded UI and unused React components were removed.
## Public research datasets

MS MARCO and Enron can now be imported into a separate searchable public corpus. Open **Knowledge → Explore beyond your files** to search installed datasets or ask the configured AI for a cited answer. Enron includes UTC date filters. Imports stream bounded subsets into SQLite; they do not populate your Gmail account or mix with private document search.

See [external dataset setup and evaluation](docs/EXTERNAL_DATASETS.md) for import commands, scale limits, attribution and benchmark methodology.
