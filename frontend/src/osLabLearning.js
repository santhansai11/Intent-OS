export const LESSONS = {
  round_robin: {number:'01', title:'Take turns fairly', concept:'Round-robin scheduling', intro:'Three equally important tasks share one CPU. Each gets a short turn, then waits for the others.', watch:'Watch P1 → P2 → P3 take turns. Each task picks up where it stopped.', try:'Try a turn length of 1, then 3. Short turns share the CPU more often; the total work stays the same.', connection:'IntentOS rotates equally ranked, eligible goals at safe boundaries. A real turn is a model decision or tool call, rather than a simulated instruction.'},
  priority: {number:'02', title:'Do urgent work first', concept:'Priority scheduling', intro:'Three tasks arrive together. P2 is high priority, P3 is medium, and P1 is low.', watch:'P2 finishes first, then P3, then P1. An expired turn does not let low-priority work skip ready high-priority work.', try:'Change the turn length. Does the completion order change? With these priorities, it should not.', connection:'IntentOS has an optional strict-priority mode. Its adaptive mode also considers waiting time and nearby deadlines to balance competing goals.'},
  preemption: {number:'03', title:'Handle arrivals & waiting', concept:'Preemption and I/O', intro:'A task starts working. More important tasks arrive later. When one waits for a device, another can use the CPU.', watch:'P3 interrupts P1; then P2 interrupts P3. P2 gives up the CPU while waiting for I/O and returns when that wait ends.', try:'Use Next step slowly. Notice that waiting for I/O is different from waiting for a turn.', connection:'A real goal can wait for input, permission or a shared resource. IntentOS can run other eligible work. It lets an active API call finish before switching; the lab can switch between instructions.'},
  memory_ipc: {number:'04', title:'Share memory & send messages', concept:'Paging, IPC and protection', intro:'Tasks use limited memory slots and exchange a message. One task deliberately requests an invalid address.', watch:'P2 waits until P1 sends 42. Memory blocks move in and out as needed. P1 eventually stops safely; the other tasks continue.', try:'Compare 1 memory slot with 4. Watch how often a block must be loaded again. The invalid-address stop is intentional.', connection:'Real intents use per-goal permissions and resource checks. This lesson separately demonstrates virtual memory and message passing inside a teaching simulator.'},
};

export const GOAL_STORY = [
  {title:'Describe a goal', concept:'Process creation', text:'“Prepare for my 4 PM meeting.” IntentOS gives the goal an identity and tracks its progress, priority and deadline.', example:'One goal, one tracked process.'},
  {title:'Choose allowed actions', concept:'Capability protection', text:'The planner proposes supported actions. IntentOS checks their arguments and your access grants. Sensitive actions may need your permission.', example:'Calendar and selected meeting files can be allowed without granting access to unrelated folders.'},
  {title:'Wait for a turn', concept:'Scheduling', text:'The scheduler chooses eligible work. Adaptive scheduling considers waiting time, nearby deadlines and priority. Strict-priority mode follows priority order.', example:'A goal waiting for a service does not have to stop other eligible goals.'},
  {title:'Run one step', concept:'Resource management', text:'A named capability performs the allowed operation. The runtime reserves its shared resource for the call and releases it afterward.', example:'Read the meeting details, then let the scheduler choose the next piece of work.'},
  {title:'Save the result', concept:'Checkpointing', text:'IntentOS records a finished step and its result in local storage. This is a checkpoint: a saved place from which the goal can continue.', example:'The calendar lookup stays recorded even if a later step fails.'},
  {title:'Resume or finish', concept:'Recovery', text:'A retryable read can resume from saved progress. If an email may already have been sent, IntentOS asks you to check before retrying. Finished goals show their results.', example:'Resume unfinished work without automatically repeating an uncertain send.'},
];

export const TERMS = [
  ['Process', 'A task with its own identity, progress and state. P1, P2 and P3 are the lab’s example processes.'],
  ['CPU', 'The worker that executes instructions. This lab has one virtual CPU, so only one task runs at a time.'],
  ['Tick', 'One unit of simulated time: an instruction attempt or memory-loading step. It is not a second.'],
  ['Ready queue', 'Tasks that could run now but are waiting for the CPU.'],
  ['Quantum', 'The maximum number of ticks in one turn before the scheduler checks rotation among equal-priority tasks.'],
  ['Context switch', 'Saving one task’s progress and loading another’s so each can continue from where it stopped.'],
  ['PC / ACC', 'Program counter: the next instruction’s index. Accumulator: the task’s current working number.'],
  ['I/O', 'Input/output work, such as waiting for a device. A waiting task releases the CPU.'],
  ['Page / frame', 'A page is a block of a task’s memory. A frame is a physical slot that can hold one page.'],
  ['Page fault / LRU', 'A page fault loads a missing block; it is not a crash. When slots are full, least recently used (LRU) replacement moves out the block unused for longest.'],
  ['IPC', 'Inter-process communication: tasks send and receive messages.'],
  ['Protection fault', 'An invalid memory access. The simulator stops the offending task while other tasks can continue.'],
];

export const priorityLabel = value => ({HIGH:'High', NORMAL:'Medium', LOW:'Low'}[value] || value);
export function stateLabel(process) {
  return {NEW:`Arrives at tick ${process.arrival}`, READY:'Waiting for a turn', RUNNING:'Using the CPU', BLOCKED_IO:'Waiting for a device', BLOCKED_IPC:'Waiting for a message', COMPLETED:'Finished', FAILED:'Stopped: invalid access'}[process.state] || process.state;
}
export function instructionText(ins) {
  if (!ins) return 'All instructions finished';
  const [op, a, b] = ins;
  return {ADD:`Add ${a} to the working number`, IO:`Wait ${a} ticks for a device`, WRITE:`Store ${b} at memory address ${a}`, READ:`Read memory address ${a}`, SEND:`Send the number ${b} to ${a}`, RECV:'Receive the next message'}[op] || op;
}

// Explain recorded execution, including past ticks, without guessing from current state.
export function explainStep(lab, tick = lab?.timeline.at(-1)?.tick) {
  const lesson = LESSONS[lab?.scenario] || LESSONS.round_robin;
  const row = lab?.timeline.find(item => item.tick === tick);
  if (!row) return {title:'Ready when you are.', what:lesson.intro, why:lesson.watch, concept:lesson.concept};
  if (!row.pid) return {title:'The CPU is waiting.', what:'No task could run during this tick.', why:'The scheduler will check arrivals and device completions again on the next tick.', concept:'Idle CPU'};
  const process = lab.processes.find(p => p.id === row.pid);
  const events = lab.events.filter(event => event.tick === tick);
  const instruction = process.program[row.before.pc];
  const fault = events.find(e => e.kind === 'protection_fault' && e.pid === row.pid);
  const evicted = events.find(e => e.kind === 'evict');
  let title = `${row.pid} did one step.`, what = `${instructionText(instruction)}. Working number: ${row.before.acc} → ${row.after.acc}.`, concept = 'Execution';
  if (fault) {
    return {title:`${row.pid} was stopped safely.`, what:`It tried address ${instruction[1]}, outside its allowed addresses 0–15. This is the lesson’s deliberate invalid access.`, why:'Only this task fails. Other tasks keep their own memory and can continue.', concept:'Memory protection'};
  }
  if (row.operation === 'PAGE FAULT') {
    return {title:`${row.pid} needs a memory block.`, what:`The required block was loaded into a memory slot. The instruction has not finished; it will try again on a later turn.`, why:evicted?`Memory was full. A least recently used block belonging to ${evicted.pid} was saved and moved out to make room.`:'The block was not in physical memory yet. Loading it takes one tick in this lab.', concept:'Page fault — a normal loading step'};
  }
  if (row.operation === 'IO') { title=`${row.pid} is waiting for a device.`; what=`It releases the CPU for ${instruction[1]} waiting ticks and becomes ready again at tick ${tick + 1 + instruction[1]}.`; concept='I/O blocking'; }
  if (row.operation === 'RECV') {
    const waiting = row.before.pc === row.after.pc;
    title = waiting?`${row.pid} is waiting for a message.`:`${row.pid} received ${row.after.acc}.`;
    what = waiting?'Its inbox was empty, so it gives up the CPU. A sender can wake it.':`The message becomes its working number. It can move to the next instruction.`;
    concept='Message passing (IPC)';
  }
  if (row.operation === 'SEND') {title=`${row.pid} sent ${instruction[2]} to ${instruction[1]}.`; what='The message goes into the receiver’s inbox. A waiting receiver becomes ready, then waits for the scheduler to choose it.'; concept='Message passing (IPC)';}
  if (row.after.pc === process.program.length) {title=`${row.pid} finished its work.`; what+=' Its memory can now be released.';}
  const preempted = events.find(e => e.kind === 'context_save' && e.message.startsWith('Higher-priority'));
  const rotated = events.find(e => e.kind === 'context_save' && e.message.startsWith('Time quantum'));
  const dispatched = events.find(e => e.kind === 'dispatch' && e.pid === row.pid);
  let why;
  if (preempted) { why=`${row.pid} was ready with a higher priority. ${preempted.pid} saved its place and waited for another turn.`; concept='Preemption'; }
  else if (rotated) {why=`${rotated.pid} used its ${lab.quantum}-tick turn. The scheduler chose the highest ready priority, rotating equally important tasks in queue order.`; if (concept==='Execution') concept='Turn taking';}
  else if (dispatched) why=`${row.pid} was next among the highest-priority ready tasks. Its saved progress was restored.`;
  else why=`${row.pid} still had time in its turn, and no higher-priority task was ready to interrupt it.`;
  if (row.operation === 'IO' || (row.operation === 'RECV' && row.before.pc === row.after.pc)) why+=' While it waits, another ready task can use the CPU.';
  return {title, what, why, concept};
}

export function resultSummary(lab) {
  const finished = lab.processes.filter(p=>p.state==='COMPLETED').length;
  const failed = lab.processes.filter(p=>p.state==='FAILED').length;
  return {title:lab.deadlocked?'The tasks cannot continue.':failed?'Lesson complete, including the deliberate stop.':'All three tasks finished.',
    text:lab.deadlocked?'The remaining tasks are waiting for messages that no runnable task can send. This is a deadlock. Restart the lesson to explore again.':`${finished} finished${failed?`, ${failed} stopped after invalid access`:''}. The CPU changed tasks ${lab.metrics.context_switches} times.${lab.scenario==='memory_ipc'?` There were ${lab.metrics.page_faults} memory loads and ${lab.metrics.evictions} replacements.`:''}`};
}
