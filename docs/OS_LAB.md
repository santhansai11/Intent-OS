# Process and memory management demonstration

Open **OS Lab** in IntentOS. Select a scenario and press **Load / reset**, then **Step one tick** or **Play demonstration**. Playback speed only controls animation; it does not change CPU time or results. Export trace saves the actual state and event log as JSON. Lab state is shared by local browser tabs and resets when the server restarts; exported traces persist.

## What was already implemented

The production runtime (`intent_kernel/runtime.py`) has durable SQLite process records, READY/RUNNING/blocked/terminal states, priority scheduling, equal-priority rotation, resource locks, bounded worker slots, dependency waiting, pause/cancel boundaries, checkpoints and crash recovery. Its adaptive policy can override priority for aged work or nearby deadlines. One quantum is **one complete model decision or capability call**, of variable wall-clock duration. It does not suspend a Python thread or Google request when a millisecond timer expires. Host memory telemetry and pressure-based concurrency reduction are not virtual-memory management.

## What is now implemented

`intent_kernel/os_lab.py` implements a bounded executable virtual machine, not a prerecorded animation. `ADD`, `READ`, `WRITE`, `IO`, `SEND` and `RECV` instructions change registers, memory or process state. No AI planning or external services are used. The browser renders backend execution state after each tick.

At each tick:

1. Admit newly arrived processes and wake completed I/O.
2. Compare the highest READY priority with the running priority. A higher-priority process preempts before the next instruction.
3. Otherwise, if the quantum expired, save context and append the process to its priority queue.
4. Dispatch the highest-priority READY process; FIFO queue order provides round robin among equals. Restore its program counter (PC) and accumulator (ACC).
5. Execute one instruction attempt. A page fault consumes one tick without advancing the PC. Record the ready queue, registers, operation and slice usage.
6. Save context on blocking, preemption, expiry or exit. Free memory on normal exit or a protection fault.

Priority is strict: HIGH > NORMAL (displayed as medium) > LOW. There is no aging in the lab. Expiry does not grant a lower-priority process a turn while higher-priority work remains ready. Long-running high-priority work can therefore starve low-priority work. A redispatch of the same PID is recorded, but is not counted as a process-to-process context switch. The first dispatch is also not a context switch. Context-switch overhead is not modeled.

## Four reproducible demonstrations

| Scenario | Configuration | Expected observation |
|---|---|---|
| Three priorities | P1 low, P2 high, P3 medium; all arrive at 0; five ADDs each | With quantum 2, P2 runs ticks 0–4, P3 5–9, P1 10–14. Every quantum is checked, even when the same PID wins again. |
| Arrivals & I/O | P1 arrives 0, P3 arrives 1, P2 arrives 2; P2 requests 3 ticks of I/O | P1 → P3 → P2. P2 blocks after tick 3, P3 runs ticks 4–6, P2 wakes at tick 7 and preempts before P3's next instruction. |
| Equal-priority rotation | All medium; quantum 2 | P1 P1 → P2 P2 → P3 P3, repeating until completion. Each ACC and PC resumes correctly. |
| Paging & messages | P2 initially waits for P1; 16 virtual bytes per process, 4-byte pages, 3 physical frames | P1 sends 42, waking P2. Reads recover values after LRU eviction. P1's intentional address-99 access fails only P1. P2 and P3 complete. |

Memory uses actual private byte arrays, per-process page tables, and a bounded shared frame pool. Only virtual addresses 0–15 are permitted. LRU writes an evicted frame to the owner's backing page; demand paging reloads it. Backing store is an in-memory teaching model, not a host swap file. Page-in is modeled as a synchronous one-tick trap, not asynchronous disk I/O. Mailboxes are separate per process; an empty receive blocks and retries on wake. A no-runnable-work/all-receivers-blocked state is reported as deadlocked.

CPU ticks include page faults and blocking instructions. Ready wait counts only READY ticks; blocked time excludes the instruction that initiated blocking. Turnaround = completion tick − arrival tick; response = first dispatch tick − arrival tick. Tests check turnaround = CPU + ready wait + blocked time for each finished process.

## Real intent scheduling

The **Apply strict priority to real intents** section enables `scheduling: strict_priority` in the existing settings API. It shares the lab's priority ordering helper, excludes blocked/resource-ineligible work, and rotates equals using their last dispatch. The default remains adaptive until selected. Strict mode disables aging and deadline overrides. It applies at safe call boundaries; in-flight calls finish normally. Execution slots still permit concurrency; use one slot in Processes to observe a serial dispatch sequence. OS Lab settings do not change production worker counts or priority policy.

## Validation and implementation map

- Backend: `intent_kernel/os_lab.py`, shared ordering in `intent_kernel/dispatch.py`.
- API: session-protected POST `/api/os-lab/reset`, POST `/api/os-lab/step`; read-only GET `/api/os-lab`.
- UI: `frontend/src/OSLab.jsx`, `frontend/src/os-lab.css`.
- Tests: `tests/test_os_lab.py` covers exact dispatch order, arrival/I/O preemption, quantum limits, register continuity, memory isolation, LRU value preservation, IPC wakeup, fault containment, per-tick accounting, settings and actual Runtime dispatch, plus HTTP authentication.
- Evidence generator: `.venv/Scripts/python.exe scripts/os_lab_demo.py` writes four JSON traces and `output/os-lab/demonstration.md`.
- Regression command: `.venv/Scripts/python.exe -m unittest tests.test_os_lab tests.test_runtime tests.test_workbench tests.test_scheduler -q`.

This is userspace OS-concept implementation. It does not replace Windows scheduling, page tables, hardware interrupts or memory protection. Real intents retain existing filesystem capability checks and durable recovery; the lab is deliberately isolated from user files, OAuth accounts and intent history.
