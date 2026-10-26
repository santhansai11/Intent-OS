export const NEEDS_ATTENTION = ['APPROVAL', 'REVIEW', 'WAITING_INPUT', 'BLOCKED'];
export const PALETTES = {
  speaking: ['#b88af4', '#f0a0c7'],
  listening: ['#e17cb9', '#53d8dc'], attentive: ['#b28bff', '#86cbfa'],
  idle: ['#a441ff', '#30c9f7'], writing: ['#c65cdb', '#8b7bff'], research: ['#458cff', '#32d6d0'],
  files: ['#c58aef', '#69b0f5'], meeting: ['#7779ed', '#66d6ee'], working: ['#5169ef', '#39c9f4'],
  approval: ['#efab36', '#ffcf76'], review: ['#ef8451', '#f3bb69'], input: ['#e49b35', '#ecd17a'],
  completed: ['#39ad7b', '#83dfad'], error: ['#e95d75', '#f3a28c'], paused: ['#8d91ae', '#bdc7dd'], offline: ['#89909e', '#b9c2cf'],
};

export function draftKind(text = '') {
  if (/\b(meet|meeting|calendar|schedule|appointment)\b/i.test(text)) return 'meeting';
  if (/\b(research|search|learn|explain|compare|knowledge)\b/i.test(text)) return 'research';
  if (/\b(file|files|folder|collect|gather|copy|move)\b/i.test(text)) return 'files';
  return text.trim() ? 'writing' : 'idle';
}

export function companionState({ task, draft = '', online = true, page = 'workspace', composing = false }) {
  if (!online) return { tone: 'offline', label: 'Reconnecting', message: 'I’m waiting for the local runtime to reconnect. You can keep drafting.' };
  const state = task?.state;
  if (state === 'APPROVAL') return { tone: 'approval', label: 'Your permission', message: 'I need your permission for one action. Let’s look at what it will do.' };
  if (state === 'REVIEW') return { tone: 'review', label: 'Let’s check', message: 'I couldn’t confirm an action finished. Please check its destination before we decide what to do next.' };
  if (state === 'WAITING_INPUT') return { tone: 'input', label: 'A quick question', message: task.question || 'I need a little more information to continue.' };
  if (composing || draft.trim()) return { tone: draftKind(draft), label: draft.trim() ? 'Following your draft' : 'Ready for your intent', message: 'I’m here while you shape your intent. Nothing starts until you choose Start intent.' };
  if (state === 'COMPLETED') return { tone: 'completed', label: 'All done', message: 'This intent is complete. Your result and any saved files are ready to review.' };
  if (['FAILED', 'BLOCKED'].includes(state)) return { tone: 'error', label: 'Needs attention', message: task.error || 'This intent needs a little help before it can continue.' };
  if (['PAUSED', 'PAUSING', 'CANCELLED', 'CANCELLING'].includes(state)) return { tone: 'paused', label: state === 'CANCELLED' ? 'Cancelled' : state === 'CANCELLING' ? 'Stopping' : 'Taking a pause', message: state === 'CANCELLED' ? 'This intent has stopped.' : 'You can inspect this intent and choose what happens next.' };
  if (state) return { tone: 'working', label: state === 'READY' ? 'Ready to run' : state === 'RECOVERY' ? 'Waiting to retry' : 'Working on it', message: task.active ? `Current step: ${task.active.replaceAll('_', ' ')}.` : state === 'RECOVERY' ? 'The runtime is waiting before its next retry.' : 'I’m following the real progress of your intent. You can inspect every step.' };
  const tips = { knowledge: 'Choose a source folder, then search your indexed documents or refresh their index.', connections: 'Connect your tools and choose which folders IntentOS can use.', processes: 'Here you can inspect running intents and adjust their execution limits.', history: 'Find an earlier intent to revisit its results and sources.', oslab: 'Choose a scenario to explore scheduling, memory, and process execution.' };
  return { tone: 'idle', label: 'Ready when you are', message: tips[page] || 'Tell me what you want to get done. Add your files, choose your access options, and start when you’re ready.' };
}

const QUESTIONS = {
  gmail_send: 'May I send this email for you?', gmail_draft: 'May I save this email as a draft?',
  files_move: 'May I move this file to the destination below?', files_copy: 'May I copy this file?',
  files_write: 'May I save this content to a file?', files_collect: 'May I create this collection of files?',
  document_export: 'May I create this document for you?', calendar_create: 'May I add this event to your calendar?',
  calendar_update: 'May I change this calendar event?', calendar_delete: 'May I delete this calendar event?',
  drive_upload: 'May I upload this file to Google Drive?', drive_download: 'May I download this Drive file?',
  drive_create_folder: 'May I create this folder in Google Drive?',
};
export function permissionQuestion(pending) {
  if (Object.hasOwn(QUESTIONS, pending?.tool)) return QUESTIONS[pending.tool];
  return `May I use ${String(pending?.tool || 'this tool').replaceAll('_', ' ')} for this intent?`;
}
const FIELD_LABELS = { to: 'Recipients', cc: 'Copy to', bcc: 'Blind copy to', subject: 'Subject', body: 'Message', path: 'File or folder', source: 'Source', destination: 'Destination', content: 'Content to save', title: 'Title', start: 'Starts', end: 'Ends', location: 'Location', description: 'Description', query: 'Search for', url: 'Web address', file_id: 'Drive file', event_id: 'Calendar event', folder_id: 'Drive folder', meet_link: 'Include a Meet link' };
export const fieldLabel = key => Object.hasOwn(FIELD_LABELS, key) ? FIELD_LABELS[key] : key.replaceAll('_', ' ').replace(/^./, value => value.toUpperCase());
export const conversationKey = task => task ? `${task.id}:${task.state}:${task.pending?.id || task.question || ''}` : 'idle';

// Pending actions take precedence, but a currently reviewed request is stable
// when snapshots reorder the background queue.
export function chooseCompanionTask(tasks, selected, pinnedId) {
  return tasks.find(t => t.id === pinnedId && NEEDS_ATTENTION.includes(t.state))
    || tasks.find(t => t.id === selected && NEEDS_ATTENTION.includes(t.state))
    || tasks.find(t => NEEDS_ATTENTION.includes(t.state))
    || tasks.find(t => t.id === selected)
    || tasks.find(t => ['RUNNING', 'READY', 'RECOVERY'].includes(t.state));
}

// A center dead zone prevents repeated side changes near the midpoint.
export function companionSide(width, pointerX, current = 'right', locked = false) {
  if (locked || width <= 640) return current;
  if (pointerX < width / 2 - 40) return 'left';
  if (pointerX > width / 2 + 40) return 'right';
  return current;
}

// Fixed edge positions keep the companion out of the middle of the workspace.
export function companionPlacement({ width, height, home, pointer, composing, panelOpen, reduced, parked, side }) {
  const mobile = width <= 640;
  const dockSize = mobile ? 76 : 112;
  const clamp = (n, low, high) => Math.min(Math.max(low, high), Math.max(low, n));
  const progress = !home || composing || panelOpen ? 1 : clamp((150 - home.top) / 260, 0, 1);
  const mix = progress * progress * (3 - 2 * progress);
  const full = home ? Math.min(home.width, home.height, width, 410) : dockSize;
  const size = full + (dockSize - full) * mix;
  const edge = side || companionSide(width, pointer.x, 'right', reduced || parked || panelOpen);
  const dockX = edge === 'left' ? 12 : width - dockSize - 12;
  const dockY = mobile || panelOpen || reduced || parked ? height - dockSize - (mobile ? 12 : 55)
    : clamp(pointer.y - dockSize / 2, 110, height - dockSize - 55);
  const homeX = home ? home.left + (home.width - full) / 2 : dockX;
  const homeY = home ? home.top + (home.height - full) / 2 : dockY;
  return { x: clamp(homeX + (dockX - homeX) * mix, 0, width - size), y: clamp(homeY + (dockY - homeY) * mix, 0, height - size), size, docked: progress > .65 };
}
