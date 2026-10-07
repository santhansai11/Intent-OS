# 🧠 IntentOS — Intent-Based Operating System Layer

> **"Don't tell the computer which application to open. Tell it what you want to accomplish."**

IntentOS is a working prototype of an **intent-based OS interaction and
resource-management layer**. The user's goal is treated as a managed
execution entity — an **Intent Process** — with priority, deadline,
resource requirements, permissions and a recoverable lifecycle. The
**Intent Kernel** schedules, authorizes, allocates, executes and recovers
on the user's behalf.

Inspired by intent-based computing; related work includes
[OSAi](https://github.com/mattias50/OSAi) (AI-native monitoring and
self-healing). IntentOS differs by making the *intent itself* the unit of
scheduling, resource management and access control.

---

## Architecture

```text
USER  ("Prepare everything for my 4 PM meeting.")
  ↓
INTENT INTERFACE        (CLI / REST API / Web UI)
  ↓
INTENT UNDERSTANDING    nlu/        TF-IDF classifier + entity extraction
  ↓
INTENT PLANNER          planner/    goal → ordered execution plan
  ↓
INTENT KERNEL           intent_kernel/
  ├─ Process Manager    intent.py + lifecycle.py   (NEW→READY→RUNNING→…)
  ├─ Intent Scheduler   scheduler/  FCFS | Priority | Round Robin | EDF
  ├─ Resource Manager   resource_manager/          (CPU / RAM / network / services)
  ├─ Permission Manager permission_manager/        (ALLOW / DENY / ASK, least privilege)
  ├─ Recovery Manager   recovery/                  (checkpoints, retry, resume)
  ├─ Intent File Manager intent_file_manager.py    (per-intent context dirs)
  └─ Service Bus        ipc/service_bus.py         (headless service registry)
  ↓
SERVICES                services/   calendar · filesystem · maps · messaging · reminder
  ↓
HOST OS                 filesystem · processes · (psutil monitoring when installed)
```

## Quick start

Requires Python 3.8+ only (standard library). Optional: `pip install psutil`
for real system monitoring.

```bash
# ── The real application ──────────────────────────────────────────────
python run_intentos.py --app              # UI + API at http://127.0.0.1:8765
#   (or: python run_intentos.py --server --port 8765)
#   open http://127.0.0.1:8765 — no Node.js required

# Research & writing: searches Wikipedia/DuckDuckGo, summarizes with a free
# LLM (pollinations.ai, no API key), and WRITES A REAL FILE to storage/workspace/
python run_intentos.py "Write a brief summary of quantum computing"
python run_intentos.py "Explain CPU scheduling algorithms"
python run_intentos.py "Create a summary about the Linux kernel"
python run_intentos.py "Summarize my latest document"

# File management: works on real folders (subject to the security allowlist)
python run_intentos.py "Find agenda.docx in d:\Intent OS\storage\documents"
python run_intentos.py "Read the file d:\Intent OS\storage\documents\meeting_notes.pdf"
python run_intentos.py "Organize my Downloads folder"
python run_intentos.py "Organize the folder d:\Intent OS\storage\sample_mixed"
python run_intentos.py "Back up the folder d:\Intent OS\storage\documents"

# Classic OS-project demos
python run_intentos.py "Prepare everything for my 4 PM meeting."
python run_intentos.py "For my compiler design meeting at 4 PM, gather the related files and save them in my Desktop meeting folder"
python run_intentos.py "Do deep research on compiler design and save it in my Documents folder"
python run_intentos.py --demo                  # 5 concurrent intents
python run_intentos.py --compare               # FCFS vs Priority vs RR vs EDF

# Run the test suite (65 tests)
python -m unittest discover -s tests
```

> **File access security:** the filesystem service only touches paths under its
> allowlist (the project directory + your user profile by default, configurable
> via `FilesystemService(allowed_roots=[...])`). Paths outside the allowlist are
> denied by the service, and write steps require WRITE permission from the
> intent's policy.

### Summarize documents and organize files

Ask for a document summary without supplying an absolute path, for example
**“Summarize my latest document”** or **“Summarize the PDF in my Documents
folder.”** IntentOS searches its document/workspace folders and your Documents,
Downloads, and Desktop folders, then extracts text from TXT, Markdown, CSV,
HTML, DOCX, PPTX, XLSX, and text-based PDF files. When several files match, it selects a
unique filename match when possible, otherwise the most recently modified
document. Scanned PDFs need OCR and are not currently supported.

File organization is available with requests such as **“Organize my Downloads
folder”** or **“Sort the files in this folder by type.”** Files are moved into
category subfolders (Docs, Images, Videos, Audio, Archives, Code, Programs,
and Other). Name a folder or give a path to organize a location other than
Downloads.

### Meeting files and deep research

For meeting requests, name the topic and time and ask IntentOS to gather or
save the related files. It checks calendar attachments and searches Documents,
Downloads, Desktop, and IntentOS storage. A natural destination such as **“my
Desktop meeting folder”** works without a full path. If no destination is
specified, files are copied into a topic-named folder under
`storage/workspace/`; the originals stay in place.

For research, name a topic and optionally a destination such as **“my
Documents folder”** or **“Research folder.”** IntentOS searches the web,
fetches source extracts, writes a research brief, and saves it to the requested
folder. Deep or thorough requests fetch more sources and produce a longer
brief.

### Scheduling is automatic

You never pick a scheduling algorithm. The kernel's `auto` scheduler inspects
the runnable set before every dispatch and adopts the right classical policy:

```text
aging (nobody starves) → deadlines near (EDF) → mixed priorities
                       → 3+ equal intents (round robin) → FCFS
```

The UI shows the live decision and its reason, e.g.
*"2 intent(s) with deadlines, nearest in 25 min - earliest-deadline-first"*.
The four classical policies remain pluggable (`--scheduler`, `/api/strategy`,
`/api/simulation`) because comparing them is part of the project's evaluation.

### Web UI

Two options, same kernel:

```bash
# Built-in UI (zero dependencies): serve, then open the printed URL
python run_intentos.py --app

# React dashboard (optional, for development)
python run_intentos.py --server           # terminal 1
cd frontend && npm install && npm run dev # terminal 2 → http://localhost:5173
```

The UI lets you submit intents (text or voice via the Web Speech API), watch
the intent lifecycle and per-step checkpoints live, see the auto-selected
scheduling policy and its reason, inject service faults to observe recovery,
inspect **every file the intents created on disk** (View = inline preview,
Open = reveal in Windows Explorer/Finder), and see kernel resource
allocations + the service registry.

### Where your files go

| Intent | Output location |
| --- | --- |
| "Write a summary of X" / "Explain X" | `storage/workspace/` and `storage/documents/research/` |
| "Back up the folder ..." | `storage/backups/<name>-<timestamp>/` |
| "Download ..." | `storage/downloads/` |
| Per-intent execution context (plan, checkpoints, log) | `storage/intent_logs/I<id>/` |

## The intent lifecycle

```text
NEW → READY → RUNNING → COMPLETED
            RUNNING → WAITING → READY      (resources short)
            RUNNING → RECOVERY → READY     (step failed, retry from checkpoint)
            RUNNING → FAILED → RECOVERY    (retries exhausted)
```

Every completed step is checkpointed to `storage/intent_logs/<id>/`:
`intent.json`, `plan.json`, `permissions.json`, `checkpoint.json`,
`execution.log` and an `output/` directory — so a failed intent resumes
where it stopped instead of restarting.

## Example output

```text
Intent I1024  [prepare_meeting]  state=COMPLETED
  Goal      :  Prepare everything for my 4 PM meeting.
  Priority  : HIGH
  Deadline  : 16:00
  OK   S1 calendar.find_event
  OK   S2 filesystem.find_documents
  OK   S3 maps.calculate_route
  OK   S4 messaging.prepare_notification
  OK   S5 reminder.set_reminder

  Result for the user:
    - Meeting : Operating Systems Review
    - Time    : 16:00
    - Location: Room 204
    - Documents: 3 related file(s) found
    - Travel  : 35 minutes (Room 204)
    - Notification: queued to user@local
    - Reminder: R… at 16:00
```

## Scheduler evaluation (`python run_intentos.py --compare`)

Same synthetic workload on one simulated resource:

| strategy    | avg wait | avg turnaround | deadline misses |
|-------------|---------:|---------------:|----------------:|
| fcfs        |    12.60 |          18.20 |               3 |
| priority    |    10.40 |          16.00 |               2 |
| round_robin |     4.00 |          19.40 |               4 |
| deadline    |     7.00 |          12.60 |      **0**      |

Deadline-aware (EDF) scheduling eliminates deadline misses on this workload,
while Round Robin minimizes waiting time — illustrating the trade-off the
Intent Kernel makes configurable.

## REST API

| Method | Route             | Body                              | Purpose                          |
|--------|-------------------|-----------------------------------|----------------------------------|
| GET    | `/api/status`     | —                                 | full kernel snapshot             |
| GET    | `/api/metrics`    | —                                 | scheduling metrics               |
| GET    | `/api/system`     | —                                 | real host resources              |
| GET    | `/api/simulation` | —                                 | scheduler comparison             |
| POST   | `/api/intents`    | `{"text": "..."}`                 | submit an intent (auto-executes) |
| POST   | `/api/strategy`   | `{"strategy": "deadline"}`        | switch scheduler at runtime      |
| POST   | `/api/faults`     | `{"service": "messaging", "count": 1}` | fault injection (recovery demo) |

## Security model (least privilege)

Each intent type has an explicit permission policy:

```text
prepare_meeting:  calendar→READ  filesystem→READ  maps→USE
                  messaging→WRITE reminder→WRITE
passwords / system_files / kernel_internals: DENIED for all intents
unknown services: default-deny, requires user confirmation (ASK)
```

Denied steps are recorded and marked BLOCKED; the rest of the plan still
completes.

## Project structure

```text
intent_kernel/     the OS layer: kernel, schedulers, resources, permissions,
                   recovery, service bus, persistence, simulation
nlu/               TF-IDF intent classifier + entity extraction (no dependencies)
planner/           goal → execution plan templates
services/          headless services: calendar, filesystem, maps, messaging, reminder
api/               stdlib REST server
frontend/          React + Vite dashboard
storage/           intents.db (SQLite), per-intent logs, documents, downloads
tests/             48 unit + integration tests (stdlib unittest)
run_intentos.py    CLI entry point
```

## What this prototype is / is not

Implemented: NLU classification, planning, intent processes with full
lifecycle, 4 schedulers, resource accounting with WAITING on overcommit,
permission boundaries with DENY/ASK, per-step checkpoints and recovery,
service registry with fault injection, SQLite persistence, per-intent file
contexts, REST API, React dashboard, scheduler simulation/evaluation, and
real file management (find/read/organize/backup with a path allowlist).

Not implemented (future work): real OS process isolation (namespaces /
cgroups), voice-input on the kernel side, LLM-backed NLU, cross-device intent
execution, dynamic service discovery over sockets/REST, permission
persistence and a true interactive confirmation loop.

## Scope note

IntentOS is **not** a bootable OS or a Linux kernel replacement — it is an
intent-centric **layer** that uses the host OS's existing mechanisms,
focusing the systems contribution on scheduling, resource management,
security and recovery at the *intent* level.
