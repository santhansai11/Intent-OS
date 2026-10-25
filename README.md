# IntentOS

**Give your goal a place to run.**

IntentOS is an AI workspace built around a durable userspace kernel. Describe a goal, and Gemini, Groq, or a local Ollama model can select capabilities, observe real results, and move the task forward. The runtime schedules decisions, enforces per-goal permissions, arbitrates resources, and checkpoints progress in SQLite.

IntentOS also includes a direct file-collection workflow that searches for related files and copies them without calling an AI model. File operations execute locally. Cloud providers receive the goal and relevant document excerpts; Ollama keeps inference local. Providers do not switch automatically, and the application does not rely on canned meeting results, simulated routes, or pretend email delivery.

For architecture details, search coverage, recovery semantics, and measured latency, see [the working model](docs/WORKING_MODEL.md).

## Highlights

### Goal workspace

- Submit natural-language goals and monitor results, workflows, sources, and activity.
- Attach multiple files as **Source** or **Reference** material for a goal.
- Use reference-guided drafting and searchable, pinnable intent history.
- Delete individual or multiple history entries. Original files and generated outputs are preserved; removing attached copies is an explicit option.
- Switch between light and dark themes.

### Local knowledge search

The Knowledge page builds an incremental local index and searches it with SQLite FTS5/BM25. Hybrid retrieval can be enabled with a local embedding model:

```powershell
ollama pull nomic-embed-text
```

Then select `nomic-embed-text` in Retrieval settings and refresh the chosen folder. Embeddings use the loopback Ollama API; remote model aliases are rejected. Index refresh is manual or requested by an intent. Changed or deleted files may remain out of date in search until the index is refreshed.

### Process studio

- Configure 1–8 total execution slots, separate planning/read limits, priorities, and prerequisite intents.
- With adaptive mode enabled, memory usage at or above 90% limits new dispatch to one slot.
- A prerequisite must complete successfully before its dependent intent can proceed. Failed or cancelled prerequisites require user action.

These are cooperative userspace execution controls, not Windows process priorities or hard real-time guarantees.

### Document processing and exports

- Gather related files into a new collection folder, with a provenance manifest and downloadable ZIP. Original files are not moved or edited.
- Export summaries as PDF, DOCX, PPTX, XLSX, TXT, Markdown, HTML, CSV, JSON, RTF, ODT, EPUB, and ZIP.
- Use local OCR for supported image and `files_ocr` workflows with PyMuPDF/Tesseract. Embedded DOCX images are not automatically OCRed.
- Search public MS MARCO and Enron datasets through **Knowledge → Explore beyond your files**. These datasets remain separate from private document search and do not populate Gmail.

## Installation

### Requirements

- Python 3.10 or newer
- Node.js 18 or newer to build the interface
- For AI planning: a Gemini or Groq API key, or [Ollama](https://ollama.com/download)

Direct topic-based file gathering does not require an AI provider.

### Install and run

From the repository root:

```powershell
python -m pip install -r requirements.txt
npm --prefix frontend install
npm --prefix frontend run build
python run_intentos.py --app
```

Open <http://127.0.0.1:8765>. The Python server serves the built React app, so a separate frontend process is not needed after building. Use `python run_intentos.py --server` to start without opening a browser; running `python run_intentos.py` also starts the server.

For development, run the server and Vite separately:

```powershell
python run_intentos.py --server
npm --prefix frontend run dev
```

Vite proxies `/api` to port 8765.

## First-time setup

1. Open **Connections** and choose **Gemini** for cloud planning or **Ollama** for local planning.
2. For Gemini, save your API key in the operating system credential store, refresh available models, and select a text model. The documented default is `gemini-3.5-flash-lite`. For Ollama, select a model already downloaded locally, such as `qwen3:4b`.
3. Add source folders under **Accessible folders** and save your provider and folder settings.
4. In Overview, choose **Ask anything** or **Gather related files · no AI needed**. For direct gathering, enter topics such as `cloud computing`; an optional date can be included, for example `AWS files saved after September 1 2026`.
5. Select **Selected folders** and choose source folders, or select **Entire computer · accessible files** for that goal.
6. Set **Save in folder** to an absolute destination such as `D:\meeting\` or `C:\Users\you\Desktop\Reports`. Missing folders are created when a file is saved. This destination is a separate per-goal grant; it does not need to be added to Connections. Leave it blank to use the workspace.
7. Use the visible output checkbox to grant creation of new collections or reports for that goal. Disable it to review those actions individually. Moves, overwrites, and calendar changes still require approval for the exact action. An explicit email request with one recipient and message context authorizes one generated email without another confirmation.

Gemini keys are not exposed in source code, settings JSON, task context, or browser responses. The password field remains empty after saving. `GEMINI_API_KEY` is supported as a fallback; a key saved in Connections takes precedence. Saving a key activates Gemini for new goals. Use **Test & use model** to verify a real response and save the selected model. Google account OAuth is separate and is not required for local files or Gemini. IntentOS does not enable billing or silently change providers when a quota is reached. See [Gemini model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) and [pricing and free-tier details](https://ai.google.dev/gemini-api/docs/pricing).

## Google integrations

See the [Google setup guide](docs/GOOGLE_SETUP.md) for Google Cloud, OAuth, Maps configuration, supported operations, and limits.

1. Copy `.env.example` to `.env`. The `.env` file is ignored by Git.
2. Create a Google Cloud project and configure the OAuth consent screen. If the app is in Testing mode, add your Google account as a test user.
3. Enable the Google Calendar API, Google Drive API, and/or Gmail API as needed.
4. Create an OAuth client of type **Web application**.
5. Add this authorized redirect URI: `http://127.0.0.1:8765/api/google/callback`. Keep it consistent with `GOOGLE_REDIRECT_URI` if you change the host or port.
6. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`.
7. In **Connections**, select the services you need, click **Connect selected services**, and complete Google's consent flow.

The implementation uses Google's authorization-code flow, a random expiring one-use state, PKCE, offline refresh, and scope checks. Tokens are stored through `keyring` in the operating system credential store, not in task context, browser storage, or the SQLite process database. On Linux, an unlocked Secret Service/keyring backend is required; Windows uses Credential Manager. There is no plaintext token fallback.

| Connection | OAuth scopes | Supported operations |
| --- | --- | --- |
| Calendar | `calendar.events` | List with pagination; create, update, and delete events after approval |
| Drive | `drive.readonly`, `drive.file` | Search, read text, download/export, and upload new files |
| Gmail | `gmail.readonly`, `gmail.compose`, `gmail.send` | Search and read messages; create drafts and send plain-text email |

Drive downloads/exports and Gmail inbox reading are supported. Downloads are capped at 10 MB and uploads at 5 MB. Existing files are preserved. Gmail attachments are listed but not downloaded. Reconnect existing accounts to approve expanded scopes. Disconnecting removes the app's locally stored credentials; revoke the grant in your Google account to remove Google-side access as well. Google may expire testing-mode or revoked refresh tokens, in which case reconnect.

**Maps is configured separately.** Enable Routes API and Places API (New), configure Google Cloud billing, and set `GOOGLE_MAPS_API_KEY`. OAuth sign-in does not enable Maps or pay API charges. Restrict the key to the required APIs and appropriate server restrictions. Place search, place details, and routing are supported.

## OS concepts implemented

IntentOS is an agent runtime organized around operating-system concepts, not a replacement operating system. Its process-management layer runs above the host operating system on Windows and Linux.

| Concept | Implementation |
| --- | --- |
| Process control block | Each intent stores a UUID, goal, lifecycle state, priority, deadline, folder/read grants, pending action, results, retry counters, and execution budget. |
| Cooperative scheduling | One quantum is one model decision or capability call. Dispatch uses aging after 30 seconds, then near-deadline EDF, then priority with round robin among peers. |
| Bounded execution | Three worker slots, one planner call at a time, and at most 48 model decisions per goal. File scans, reads, responses, prompts, and writes are bounded. Direct collection bypasses planning. |
| Resource arbitration | Exclusive named resources include the local model, filesystem, Calendar, and Gmail. Each quantum acquires one resource, avoiding hold-and-wait lock cycles. |
| Capability security | A fixed registry validates each tool and its arguments. Reads require per-goal scope or one-action approval. Other writes and sends require approval of immutable action IDs and arguments. |
| Folder boundaries | Folder grants constrain file operations to canonical paths. Hidden paths, credential files, and private kernel state are excluded. These are application boundaries, not OS memory isolation. |
| Journaling and checkpoints | SQLite WAL with FULL synchronization. Process checkpoints and audit events are committed together after each decision and completed call. |
| Crash recovery | Queued processes are restored at startup. Completed steps are not automatically replayed. Interrupted reads can retry; interrupted writes enter REVIEW. |
| Pause and cancel | These controls are cooperative. An in-flight call finishes and its effect is recorded before state changes; cancellation cannot undo an email already sent. |
| Observability | Server-sent events update the UI with the queue, scheduler decisions, resource owners, checkpoints, and audit trail. |

SQLite cannot atomically transact with Gmail or the filesystem, so IntentOS does not promise exactly-once external effects. If a service times out after a write or the process stops between a write and its checkpoint, inspect the destination before retrying. Calendar creation uses a stable operation-derived event ID. File writes use atomic replacement; interrupted copies or moves may need reconciliation.

Scheduling is cooperative, not real-time preemptive scheduling. Active model or HTTP calls can delay urgent goals that need the same resource, so deadlines are best effort. CPU/RAM readings come from the host monitor, but the runtime does not enforce cgroups, OS process quotas, containers, or a security sandbox against hostile local software. Folder checks do not replace OS isolation against concurrent filesystem tampering.

## Capabilities

The capability registry exposes tools for:

- System status
- File listing, search, reading, writing, copying, and moving
- Topic search and file collection
- Document export and PDF text replacement/merging
- Knowledge search, Wikipedia extracts, and multi-source research
- Calendar list/create/update/delete
- Drive search/read/download/upload
- Gmail search/read/draft/send
- Maps places/details/routes

PDF and Office readers extract existing text but do not perform OCR by default. PDF editing creates new copies and refuses to overwrite inputs or existing outputs. Text replacement supports exact, single-line ASCII text in a single horizontal style span, uses standard fonts, and may shrink text to fit. Scanned, rotated, signed, encrypted, and form PDFs require specialized editors for text changes. PDF merges preserve page order and interactive form fields, using separate field namespaces per input. Inputs are limited to 20 MB / 200 pages each; merges are limited to 500 pages / 100 MB total. Research connectors query Wikipedia, Crossref, and Open Library concurrently and return excerpts, metadata, source URLs, and provider failures. This is limited research, not arbitrary browser automation or full-text access to every source.

To add a tool, register its schema, read scope, side-effect flag, handler, and resource identity in `services/capabilities.py`. The planner receives the registry automatically. Keep credentials out of the tool catalog and observations.

## File collection and search limits

File gathering scans filenames and cached document text, copies matches into a **new** folder, and creates a provenance manifest plus downloadable ZIP. Original files are never moved or edited. Duplicate filenames receive stable suffixes. Search matches whole topic phrases: `operating system` does not match `system` alone; separate alternatives with commas, such as `operating system, OS`. Direct-mode destination instructions are rejected with guidance to use the folder field or **Ask anything**. Matching is lexical, so incidental mentions may match; it is not semantic classification.

Summary exports create real files in the supported formats listed above. Office formats use their actual document containers rather than renamed text. PPTX paginates content into slides, XLSX/CSV organize sections into rows, and ZIP contains Markdown. Unsupported extensions are rejected. Scanned-document OCR and arbitrary file-format conversion are not implemented.

Whole-computer access means files readable by the current OS account, with credential, hidden, kernel-state, and OS-managed-directory exclusions. It does not elevate permissions. **Search in** shows actual source folders; the output folder does not add search locations. Scans discover filenames first, then inspect cached document text. Last-modified filters run before extraction. Nested code projects and dependency/build/tool directories are skipped unless a project root is explicitly selected; direct mode offers **Include nested code projects**. A durable SQLite queue yields to the scheduler every 250 items or about two seconds and continues until finished. Live counts distinguish discovered files from contents checked. Pause/restart preserves progress; copying starts after scanning finishes. Content search examines the first 16,000 extracted characters of supported documents up to 10 MB, without OCR. Prior IntentOS collection folders are excluded to avoid repeatedly collecting copies. Copies are limited to 500 MB per collection.

Additional limits include 12 uploads per intent, 100 MB per upload, 25,000 queued entries per index job, 2,000 chunks per document, and 300 pages per PDF indexing job. Some readers return bounded excerpts; comprehensive summaries must follow pagination or disclose partial coverage. Dense similarity currently scans permitted vectors, so performance at 100,000 files has not been established.

## Local OCR

Place English OCR data from the official [tessdata_fast repository](https://github.com/tesseract-ocr/tessdata_fast) at `storage/runtime/ocr/eng.traineddata`. It is installed on the original development laptop. Uploaded images and `files_ocr` use local OCR; embedded DOCX images are not automatically OCRed.

## Ollama behavior

The Ollama integration uses its native [chat endpoint](https://docs.ollama.com/api/chat) and [JSON-schema structured output](https://docs.ollama.com/capabilities/structured-outputs), preserving the model's default reasoning mode. Small prompts use an 8K context; longer histories use 16K. A local decision can take minutes on limited hardware, so the request timeout is ten minutes. There is no cloud fallback and the app does not trigger model downloads. `OLLAMA_HOST` must be loopback. The planner checks model metadata before sending context and rejects cloud-backed models and aliases. Local model quality affects complex-goal planning; unsupported capabilities are not invented.

## Example requests

- “Find the latest document in my workspace and summarize the action items.”
- “Gather my cloud computing files into a separate meeting folder. Keep the originals unchanged.”
- “Prepare a meeting pack from my project files, then save a summary of those documents as a DOCX.”
- “Explain deadlock prevention and save a PDF in my workspace.”
- “Research how operating systems prevent deadlocks and save a brief with sources.”
- “List my calendar events tomorrow and help me prepare for the first meeting.”
- “Create a meeting at 4 PM tomorrow titled Project review.”
- “Calculate a walking route from [starting address] to [destination].”
- “Write an email to [full email address] with the meeting notes, then ask me to approve sending it.”

## Storage and API

Important runtime paths:

- `storage/runtime/kernel.sqlite3` — private intent state and audit events; ignored by Git.
- `storage/runtime/settings.json` — selected provider, models, and configured folders; no API keys.
- `storage/runtime/search-cache.sqlite3` — local document extraction cache keyed by canonical path, modification time, and size.
- `storage/runtime/kernel.lock` — host-level single-instance lock.
- `storage/workspace/` — user-visible artifacts preserved across restarts.
- OS credential store — Gemini key and Google tokens, namespaced by runtime directory.

`INTENTOS_DATA_DIR` can select a separate runtime directory. IntentOS is a **single-user loopback application**. It rejects untrusted Host/Origin headers and requires a per-server session token on mutations. It has no multi-user authentication; do not expose it on a public interface. Local software running as the OS account can access the app and its files. Task history is stored locally without application-level encryption, so protect the OS account and backups.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/status`, `/api/events` | Snapshot and live SSE stream |
| GET | `/api/models?provider=gemini`, `/api/models?provider=ollama`, `/api/system` | Model discovery and host metrics |
| GET | `/api/session` | Session token for `X-IntentOS-Token` on JSON POST requests |
| POST | `/api/intents` | Goal, priority, deadline, roots, search roots, output folder, scopes, access mode, auto outputs, and optional direct workflow |
| POST | `/api/intents/{id}/{action}` | Approve, deny, reply, pause, resume, cancel, retry, or skip |
| POST | `/api/settings`, `/api/ai/key` | Provider/model/folder settings and secure Gemini key storage/removal |
| POST | `/api/google/connect`, `/api/google/disconnect` | Google connection lifecycle |
| GET | `/api/artifact?intent={id}&step={id}` | Download a checkpointed artifact |

Additional routes include `POST /api/uploads` (authenticated binary body with URL-encoded `X-Filename`), `POST /api/uploads/remove`, `POST /api/history/delete`, `GET /api/knowledge`, and `POST /api/knowledge/search`. Intent submission also accepts `attachments` and `depends_on`; intent controls include `pin` and `priority`.

## Verification

Run the test suite and build the frontend:

```powershell
python -m unittest discover -s tests
npm --prefix frontend test
npm --prefix frontend run build
```

Runtime regression tests cover real file writes/downloads, approvals and denials, folder escapes, schema validation, fairness, EDF, aging, cancellation, resource contention, restart recovery, OAuth state/PKCE/refresh, and API CSRF/Host checks. Model decisions and Google HTTP responses are test doubles in these tests; passing tests do not establish live model quality or access to a Google account. The symlink test is skipped where the host cannot create symlinks.

`tests/test_collections_exports.py` reopens all 13 export formats and verifies topic matching, caching, source hashes, duplicate filenames, new-destination enforcement, search-folder isolation, direct execution without AI, narrow output grants, provider pinning, and key redaction. For an opt-in Gemini workflow test using synthetic files through the real HTTP API, run:

```powershell
python scripts/workflow_live_test.py
```

Add `--combined-only` to test the gathering-plus-brief workflow. These scripts preserve existing configured folders and leave Gemini selected. Reports are written under ignored `storage_test/`.

For RAG evaluation, the Review 2 draft and benchmark data are in `docs/review2/`. Reproduce the 12-query experiment with:

```powershell
python scripts/rag_evaluation.py --corpus "C:\Example\Documents\Lab" --data-root storage_test/rag-evaluation/runtime --output storage_test/rag-evaluation/results.json
```

For a live PDF workflow, start the server, install `qwen3:4b` in Ollama, and run `python scripts/pdf_live_test.py`. This explicit test selects that model, grants a newly created synthetic fixture folder, submits a natural-language request through the API, approves only the two expected PDF actions, saves outputs separately, checks page content/order, and compares the originals folder's SHA-256 manifest. Each run writes a `verification.json` report under `output/pdf/`. Normal app writes still require user approval. `tests/test_pdf_tools.py` also covers overwrite prevention, path grants, form preservation, and failure behavior.

Measured on the development machine on 9 October 2026: direct collection took 0.378 s, Gemini collection 26.849 s (including a retry after HTTP 503), PDF summary 12.755 s, and a combined meeting pack plus source-based Markdown brief 28.135 s. These small-fixture measurements are not whole-disk speed guarantees; see the working model for test records.

## Project layout

```text
intent_kernel/runtime.py     Durable process manager, scheduler, workers, audit, and recovery
intent_kernel/config.py      Local settings and environment loading
planner/agent.py             Ollama structured next-action planner
planner/router.py             Per-intent provider routing and compact Gemini context
services/capabilities.py     Validated tool registry and file boundaries
services/collections.py      Cached topic search, source-preserving copies, and manifests
services/documents.py        Thirteen summary export formats
services/gemini.py           Bounded Gemini transport and secure API-key storage
services/connections.py      Bounded HTTP, Google OAuth, and OS credential storage
api/server.py                Loopback HTTP/SSE API and React static serving
frontend/src/                Responsive task workspace, approvals, and kernel inspector
tests/test_runtime.py        Runtime and integration regression tests
```

The original classifier, template planner, simulated services, and classical scheduler comparison remain only for educational demonstrations and regression tests. `--demo` explicitly labels synthetic results; `--compare` compares FCFS/Priority/RR/EDF on a synthetic workload. Neither powers the application. Existing documents and artifacts are preserved; the obsolete duplicate embedded UI and unused React components were removed.

## Public research datasets

MS MARCO and Enron can be imported into a separate searchable public corpus. Open **Knowledge → Explore beyond your files** to search installed datasets or ask the configured AI for a cited answer. Enron supports UTC date filters. Imports stream bounded subsets into SQLite and do not populate Gmail or mix with private document search.

See [external dataset setup and evaluation](docs/EXTERNAL_DATASETS.md) for import commands, scale limits, attribution, and benchmark methodology.

## Groq planning

Choose **Groq** in Connections, save your API key, and use **Test & use model**. The default model is `openai/gpt-oss-120b`; refresh models to choose another text model that supports JSON responses. Saving a key activates that provider for new intents. Existing intents retain their provider, and failures never cause an automatic provider switch.

Groq receives the goal and relevant excerpts through its chat completions API. Files, Gmail and other capabilities still execute through the same permission checks and durable checkpoints. The connection test sends only a small test message, without files. Keys are saved in the OS credential store separately from Gemini; settings and API responses expose only whether a key exists. `GROQ_API_KEY` and `GROQ_MODEL` are optional environment overrides (a saved key takes precedence).

API clients can pass `provider: "groq"` to `/api/ai/key` and `/api/ai/test`, and discover models with `/api/models?provider=groq`. Omitting the provider on key/test requests retains Gemini compatibility. See [Groq API documentation](https://console.groq.com/docs/api-reference) and [JSON response support](https://console.groq.com/docs/structured-outputs).


Groq planning uses a bounded request with compact policy text, only granted capability schemas, and no duplicated document bodies. Large evidence is summarized in UTF-8-safe chunks and cached under the runtime's `groq_context/` directory, keyed by content, model and summarization instructions. Every supplied chunk is processed; originals remain in checkpoints. Summaries are explicitly labeled as lossy evidence, and missing source coverage is still reported. Fixed user instructions, execution records and schema constraints are not silently truncated. If they alone exceed the request budget, the planner stops with an actionable error. A rejected oversized planning call receives one smaller-budget retry; capabilities are not replayed. Groq rate-limit retries honor the provider's reset delay. Actual account allowances may still require a waiting period or choosing a different provider.


Drive folder workflows use `drive_search`, `drive_create_folder`, then `drive_upload` with the returned folder ID as `parent_id`. Folder creation is a checkpointed account write and follows the same action approval/recovery rules as uploads. Enable **Google Drive API** in the OAuth client's Cloud project; Google sign-in alone does not enable it. Disabled API and insufficient-scope errors now explain the required setup instead of showing a bare HTTP 403.


Google Meet tools now support reusable links, space status, ending an app-created call, conference history, participants and existing recording/transcript metadata and transcript entries. Reconnect with Meet selected to grant its OAuth scopes. Calendar can create scheduled Meet links using `meet_link="true"` and retrieve the resulting link with `calendar_get`. Connections includes read-only service checks and secure Maps key entry; follow [Google setup](docs/GOOGLE_SETUP.md) for required APIs and billing. Maps authentication is separate from Google OAuth.
## OS Lab: process and memory management

Open **OS Lab** in the sidebar for an executable virtual CPU with strict priority,
configurable instruction quanta, context save/restore, I/O blocking, IPC mailboxes,
private page tables, LRU replacement and fault isolation. Play or single-step four
scenarios and export their actual traces. Real intents also offer a strict priority
mode at cooperative API/tool call boundaries; this does not preempt Windows threads.
See [implementation and demonstration guide](docs/OS_LAB.md). Generate reproducible
evidence with `.venv/Scripts/python.exe scripts/os_lab_demo.py`.

## Orbii companion

Click Orbii to open text chat. Opening the conversation never starts the microphone. Choose **Use voice** explicitly in the chat or under the main intent draft when you want microphone input. Allow microphone access through the browser prompt, speak, stop, then review the editable transcript and send it. Recognition may use the browser provider’s online service; unavailable or denied microphones leave typing available. Voice never submits or approves an action automatically.

Orbii has expressive eyes, blinks, and changes colors while listening, thinking, or speaking. It shrinks as the hero scrolls away, docks on the cursor’s side of the screen, and follows its vertical position. It stays still during conversation and completion popups so its controls remain reachable. **Stay on this side**, **Pause motion**, and system reduced-motion preferences are supported. Small touch screens use a stable corner position. Newly completed intents bring happy eyes and an **Intent finished** popup. **Read answer** opens the result; **Discuss this result** adds that completed answer as reference for chat.

Normal conversation uses `/api/chat` and the configured AI provider, independently of the scheduler. It never creates an intent, writes to intent history, or executes tools. Recent messages are kept in this tab, with bounded context sent for follow-up replies. **New chat** clears that conversation; refreshing also clears it. **Use as intent** copies the message to an editable workspace draft; only **Start intent** submits it. Actual intent permission requests retain their exact action details and explicit choices.

Each chat request includes a server-generated description of IntentOS, its registered capabilities and current locally recorded integration status. Orbii can explain Gmail, Drive, Calendar, Meet and Maps support without confusing chat with execution. This context excludes credentials and account contents. Recorded authorization is not a live connection test; use Connections to check access. Google integrations use built-in APIs rather than MCP servers.

Each visit starts with text replies, including when upgrading from older versions that enabled speech automatically. Select **Text + voice** under **Reply format** to opt into spoken replies, or use **Read aloud** for just one response. Spoken replies use browser speech synthesis, with a gentle rate and pitch and a preference for available feminine English voices. Open **Voice options** to select an installed voice or preview it. Select **Text** to turn automatic speech off. **Stop speaking** interrupts playback. Starting microphone input, closing the conversation, navigating, or hiding the tab stops playback. Voice availability depends on the device/browser, and some voices use online services. Text remains available if playback is unsupported or blocked. No speech API key is needed.

After updating this feature, rebuild the frontend and restart the Python server to load the chat endpoint.

## Keeping local data private

Copy `.env.example` to `.env` and supply credentials locally, or save supported API keys through Connections in the OS credential store. The example contains blank credential values. Never put keys in frontend source or `VITE_` environment variables, which are exposed to the browser.

Git excludes local environment files, runtime storage, generated outputs, temporary audits, databases and common credential exports. Existing bundled synthetic fixtures remain tracked. Do not force-add ignored files: task history, uploaded documents, screenshots and generated reports can contain private account data even when they contain no API keys.
