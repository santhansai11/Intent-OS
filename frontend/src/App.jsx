import React, { useEffect, useState } from 'react';
import { api } from './api';

const TERMINAL = ['COMPLETED', 'CANCELLED', 'FAILED'];
const NEEDS = ['APPROVAL', 'WAITING_INPUT', 'BLOCKED', 'REVIEW'];
const SCOPE_NAMES = { files: 'Local files', web: 'Web research', calendar: 'Calendar', drive: 'Drive', maps: 'Maps', gmail: 'Gmail' };
const time = value => new Date(value * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const short = value => value?.slice(0, 8);

function Icon({ name, size = 19 }) {
  const paths = {
    spark: <><path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3Z"/><path d="m20 2 .7 2.3L23 5l-2.3.7L20 8l-.7-2.3L17 5l2.3-.7Z"/></>,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
    activity: <path d="M2 12h5l3-8 4 16 3-8h5"/>,
    plug: <><path d="M8 3v5m8-5v5M7 8h10v4a5 5 0 0 1-10 0ZM12 17v5"/></>,
    arrow: <path d="M12 20V4m-6 6 6-6 6 6"/>,
    file: <><path d="M14 3H5v18h14V8Zm0 0v5h5M8 12h8m-8 4h6"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    chevron: <path d="m9 5 7 7-7 7"/>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.spark}</svg>;
}

function Badge({ state }) { return <span className={'badge state-' + state}>{state.replaceAll('_', ' ').toLowerCase()}</span>; }

export default function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [connected, setConnected] = useState(false);
  const [page, setPage] = useState('workspace');
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [goal, setGoal] = useState('');
  const [priority, setPriority] = useState('NORMAL');
  const [deadline, setDeadline] = useState('');
  const [scopes, setScopes] = useState(['files', 'web']);
  const [roots, setRoots] = useState(null);
  const [showOptions, setShowOptions] = useState(false);
  const [accessMode, setAccessMode] = useState('selected');
  const [autoOutputs, setAutoOutputs] = useState(true);
  const [mode, setMode] = useState('agent');
  const [destination, setDestination] = useState('');
  const [outputFolder, setOutputFolder] = useState('');
  const [exportFormat, setExportFormat] = useState('');

  useEffect(() => {
    api('/status').then(setSnapshot).catch(e => setError(e.message));
    const stream = new EventSource('/api/events');
    stream.addEventListener('snapshot', event => { setSnapshot(JSON.parse(event.data)); setConnected(true); });
    stream.onerror = () => setConnected(false);
    return () => stream.close();
  }, []);

  const tasks = snapshot?.intents || [];
  const task = tasks.find(t => t.id === selected);
  const attention = tasks.filter(t => NEEDS.includes(t.state));
  const active = tasks.filter(t => !TERMINAL.includes(t.state));
  async function perform(fn) {
    setError(''); setBusy(true);
    try { return await fn(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  const control = (action, data = {}) => perform(() => api(`/intents/${selected}/${action}`, data));
  const submit = event => {
    event.preventDefault();
    if (!goal.trim()) return;
    perform(async () => {
      const folder = outputFolder.trim() || snapshot.config.workspace;
      const requested = destination.trim();
      const target = requested ? (/^(?:[a-z]:[\\/]|[\\/])/i.test(requested) ? requested : `${folder}/${requested}`) : '';
      const collectionPath = target || `${folder}/${goal.slice(0, 50).replace(/[^\p{L}\p{N}-]+/gu, '-').replace(/^-|-$/g, '') || 'collection'}-${Date.now()}`;
      const text = mode === 'collect' ? `Gather files about ${goal} into ${collectionPath}. Preserve originals.` : goal + (exportFormat ? `\nSave the result as a ${exportFormat.toUpperCase()} file${target ? ` at ${target}` : ` in ${folder}`}.` : target ? `\nSave the result at ${target}.` : outputFolder.trim() ? `\nSave any generated files in ${folder}.` : '');
      const created = await api('/intents', { text, priority, deadline: deadline ? new Date(deadline).toISOString() : null,
        scopes: ['system', ...scopes], roots: [...new Set([...(roots || [snapshot.config.roots[0]]), snapshot.config.workspace])],
        access_mode: accessMode, auto_outputs: autoOutputs, search_roots: roots || [snapshot.config.roots[0]], output_folder: folder,
        ...(mode === 'collect' ? { workflow: { type: 'collect', query: goal, destination: collectionPath } } : {}) });
      setSelected(created.id); setGoal(''); setPage('workspace');
    });
  };
  function openTask(t) { setSelected(t.id); setPage('workspace'); }

  return <div className="shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="IntentOS home"><span className="brand-symbol"><Icon name="spark" size={25}/></span><span>intent<span className="brand-os">OS</span><small>YOUR PERSONAL RUNTIME</small></span></a>
      <button className="new-intent" onClick={() => { setSelected(null); setPage('workspace'); }}><Icon name="plus"/> New intent <span>↗</span></button>
      <div className="nav-label">WORKSPACE</div>
      <nav>
        <button className={page === 'workspace' ? 'nav active' : 'nav'} onClick={() => setPage('workspace')}><Icon name="grid"/> Overview</button>
        <button className={page === 'processes' ? 'nav active' : 'nav'} onClick={() => setPage('processes')}><Icon name="activity"/> Intent processes <span className="count">{active.length}</span></button>
        <button className={page === 'connections' ? 'nav active' : 'nav'} onClick={() => setPage('connections')}><Icon name="plug"/> Connections</button>
      </nav>
      <div className="nav-label recent-label">RECENT INTENTS <span>{tasks.length}</span></div>
      <div className="recent-list">{tasks.slice(0, 10).map(t => <button key={t.id} className={'recent ' + (selected === t.id ? 'chosen' : '')} onClick={() => openTask(t)}><span className={'status-dot state-' + t.state}/><span>{t.goal}</span></button>)}{!tasks.length && <p className="sidebar-empty">Your goals will live here.<br/>Ready when you are.</p>}</div>
      <div className="sidebar-bottom"><span className={'live-dot ' + (connected ? '' : 'offline')}/><div>{connected ? 'Kernel online' : 'Reconnecting…'}<small>Local execution · durable state</small></div><span className="version">v2</span></div>
    </aside>

    <div className="main-shell">
      <header className="topbar"><div><span className="breadcrumb">Personal workspace</span><span className="slash">/</span><b>{page === 'connections' ? 'Connections' : page === 'processes' ? 'Intent processes' : 'Overview'}</b></div><div className="topbar-right"><span className="local-pill"><Icon name="shield" size={14}/> Local-first</span><span className="avatar">You</span></div></header>
      {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
      <div className="workspace-layout">
        <main className="content">
          {page === 'connections' ? <Connections snapshot={snapshot} perform={perform} busy={busy}/> : page === 'processes' ? <>
            <div className="eyebrow">PROCESS MANAGER</div><h1>Every goal, accounted for.</h1><p className="lede">Persistent identity. Explicit permissions. A checkpoint after every action.</p>
            <div className="process-table"><div className="table-heading"><span>INTENT</span><span>STATE</span><span>CHECKPOINTS</span></div>{tasks.map(t => <button className="table-row" key={t.id} onClick={() => openTask(t)}><span><b>{t.goal}</b><small>{short(t.id)} · {t.priority.toLowerCase()} priority</small></span><Badge state={t.state}/><span>{t.steps.length} <Icon name="chevron" size={14}/></span></button>)}{!tasks.length && <Empty/>}</div>
          </> : task ? <IntentDetail key={task.id} task={task} control={control} busy={busy} events={snapshot.events.filter(e => e.intent_id === task.id)}/> : <>
            <div className="eyebrow"><span className="tiny-line"/> LESS SWITCHING. MORE DOING.</div>
            <h1>What’s on your mind?</h1><p className="lede">Gather your files. Turn ideas into documents.<br/>Your intent kernel keeps every step accountable.</p>
            <form className="composer" onSubmit={submit}>
              <div className="workflow-controls"><label>Workflow<select value={mode} onChange={e => setMode(e.target.value)}><option value="agent">Ask anything</option><option value="collect">Gather related files · no AI needed</option></select></label><label>Folder access<select value={accessMode} onChange={e => setAccessMode(e.target.value)}><option value="selected">Selected folders</option><option value="system">Entire computer · accessible files</option></select></label></div>
              <p className="access-note"><strong>Search in: </strong>{accessMode === 'system' ? snapshot?.config.system_roots?.join(', ') : (roots || (snapshot ? [snapshot.config.roots[0]] : [])).join(', ') || 'No source folders selected'}<br/>Choose Entire computer to search all accessible drives, or choose specific source folders under read grants below. Save in folder only sets the output location.</p>
              <label className={mode === 'collect' ? 'field-title' : 'sr-only'} htmlFor="goal">{mode === 'collect' ? 'Topics to match' : 'Your goal'}</label><textarea id="goal" value={goal} onChange={e => setGoal(e.target.value)} placeholder={mode === 'collect' ? 'operating system, OS' : 'Prepare for my meeting, find a document, research an idea…'} maxLength={12000} onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(e); }}/>
              {mode === 'collect' && <p className="access-note">Use topic phrases separated by commas. “operating system” matches that phrase, not “system” alone. Put the destination in the folder field below. For a full instruction, choose Ask anything.</p>}
              <div className="workflow-controls"><label className="grow">Save in folder<input value={outputFolder} onChange={e => setOutputFolder(e.target.value)} placeholder={snapshot?.config.workspace || 'D:\\meeting'}/></label></div>
              <p className="access-note">Choose any writable folder, for example D:\meeting. It can already exist; missing folders are created when saving. This grants the goal access to that output folder without adding it to source searches. Leave blank to use the workspace.</p>
              <div className="workflow-controls">{mode === 'agent' && <label>Output format<select value={exportFormat} onChange={e => setExportFormat(e.target.value)}><option value="">Use my request</option>{['pdf','docx','pptx','xlsx','txt','md','html','csv','json','rtf','odt','epub','zip'].map(f => <option key={f} value={f}>{f.toUpperCase()}</option>)}</select></label>}<label className="grow">{mode === 'collect' ? 'New collection folder name (optional)' : 'Output filename (optional)'}<input value={destination} onChange={e => setDestination(e.target.value)} placeholder={mode === 'collect' ? 'OS-files' : 'meeting-summary.pdf'}/></label></div>
              <p className="access-note">Outputs go to {outputFolder.trim() || snapshot?.config.workspace || 'the workspace'}. Collections get a new subfolder; existing files are preserved.</p>
              <label className="folder-check output-grant"><input type="checkbox" checked={autoOutputs} onChange={e => setAutoOutputs(e.target.checked)}/>Allow this goal to create new collections and reports automatically. Existing files stay unchanged.</label>
              {accessMode === 'system' && <p className="access-note">Includes {snapshot?.config.system_roots?.join(', ')}. OS-managed directories, credentials and unreadable files are excluded. Scans continue in batches; pause or cancel takes effect between batches.</p>}
              {snapshot?.config.provider === 'gemini' && mode === 'agent' && <p className="access-note">Gemini receives your goal and the file excerpts needed for it. File operations run on your computer.</p>}
              <div className="composer-bottom"><button className="text-button" type="button" onClick={() => setShowOptions(!showOptions)}><Icon name="shield" size={16}/> {scopes.length} read grants <span>⌄</span></button><div className="submit-wrap"><span>Ctrl + Enter</span><button className="run-button" disabled={busy || !goal.trim() || !snapshot} title="Run intent" aria-label="Run intent"><Icon name="arrow"/></button></div></div>
              {showOptions && <div className="intent-options"><div className="field-row"><label>Priority<select value={priority} onChange={e => setPriority(e.target.value)}><option>LOW</option><option>NORMAL</option><option>HIGH</option></select></label><label>Deadline (local time)<input type="datetime-local" value={deadline} onChange={e => setDeadline(e.target.value)}/></label></div><span className="field-title">Allow reads for this goal</span><div className="check-row">{Object.entries(SCOPE_NAMES).map(([key, title]) => <label key={key}><input type="checkbox" checked={scopes.includes(key)} onChange={e => setScopes(e.target.checked ? [...scopes, key] : scopes.filter(s => s !== key))}/>{title}</label>)}</div><span className="field-title">Selected source folders</span>{snapshot?.config.roots.map(root => <label className="folder-check" key={root}><input type="checkbox" checked={(roots || [snapshot.config.roots[0]]).includes(root)} onChange={e => { const current = roots || [snapshot.config.roots[0]]; setRoots(e.target.checked ? [...current, root] : current.filter(r => r !== root)); }}/><span>{root}</span></label>)}<small>Choose source folders here. Add more paths in Connections. Moves, overwrites and sends require separate approval.</small></div>}
            </form>
            <div className="composer-caption"><span className="live-dot"/> {mode === 'collect' ? 'Direct local workflow · zero AI calls' : snapshot?.config.provider === 'gemini' ? snapshot.config.gemini_model : snapshot?.config.model || 'Choose a model in Connections'}<span>Copies, exports, and durable checkpoints.</span></div>
            {mode === 'agent' && !(snapshot?.config.provider === 'gemini' ? snapshot.config.gemini_configured : snapshot?.config.model) && <button className="setup-banner" onClick={() => setPage('connections')}><Icon name="plug"/><span><b>Connect your AI provider</b><small>Use Gemini for cloud planning or Ollama for private inference.</small></span><Icon name="chevron"/></button>}
            <div className="section-title"><h2>A little inspiration</h2><span>ONE GOAL. MANY POSSIBILITIES.</span></div>
            <div className="suggestions">{[
              ['clock', 'Walk in prepared', 'Find my next calendar meeting and help me prepare a briefing.'],
              ['file', 'Build a meeting folder', 'Gather files related to cloud computing into a new meeting folder. Keep the originals unchanged.'],
              ['spark', 'Create a topic brief', 'Summarize how operating systems prevent deadlocks and save a PDF brief with sources.'],
            ].map(([icon, title, text]) => <button key={title} onClick={() => setGoal(text)}><span className={'suggestion-icon ' + icon}><Icon name={icon}/></span><b>{title}</b><p>{text}</p><span className="card-arrow">↗</span></button>)}</div>
            <div className="section-title"><h2>{attention.length ? 'Needs your attention' : 'Your recent activity'}</h2><button className="text-button" onClick={() => setPage('processes')}>View all <span>→</span></button></div>
            <div className="activity-list">{(attention.length ? attention : tasks).slice(0, 4).map(t => <button className="activity-row" key={t.id} onClick={() => openTask(t)}><span className="activity-icon"><Icon name={NEEDS.includes(t.state) ? 'shield' : 'activity'}/></span><span className="activity-text"><b>{t.goal}</b><small>{t.steps.length} checkpoints · {time(t.created_at)}</small></span><Badge state={t.state}/><Icon name="chevron" size={16}/></button>)}{!tasks.length && <Empty/>}</div>
          </>}
          <footer>BUILT AROUND YOUR INTENT <span>Userspace kernel · Runs on your operating system</span></footer>
        </main>
        <KernelPanel snapshot={snapshot} connected={connected}/>
      </div>
    </div>
  </div>;
}

function Empty() { return <div className="empty"><span className="empty-icon"><Icon name="activity"/></span><b>A clear runway.</b><p>Start an intent above. Its progress and results will appear here.</p></div>; }

function IntentDetail({ task, control, busy, events }) {
  const [reply, setReply] = useState('');
  const [risk, setRisk] = useState(false);
  const pending = task.pending;
  return <>
    <div className="detail-heading"><span className="eyebrow">INTENT / {short(task.id)}</span><Badge state={task.state}/></div>
    <h1 className="task-title">{task.goal}</h1>
    <div className="task-meta"><span><Icon name="clock" size={15}/> {time(task.created_at)}</span><span>{task.priority.toLowerCase()} priority</span><span>{task.steps.length} checkpoints</span>{task.deadline && <span className={task.deadline_missed ? 'overdue' : ''}>Due {new Date(task.deadline * 1000).toLocaleString()}</span>}</div>
    <div className="task-controls">{['READY', 'RUNNING', 'RECOVERY'].includes(task.state) && <button disabled={busy} onClick={() => control('pause')}>Pause</button>}{['PAUSED', 'BLOCKED'].includes(task.state) && <button disabled={busy} onClick={() => control('resume')}>Resume from checkpoint</button>}{!TERMINAL.includes(task.state) && !['REVIEW', 'CANCELLING'].includes(task.state) && <button disabled={busy} onClick={() => control('cancel')}>Cancel intent</button>}</div>
    {task.active && <div className="running-bar"><span className="spinner"/>{task.active}<span>{task.active === "Planning next action" ? (task.provider === "gemini" ? "Gemini planning" : "Ollama planning") : "Local capability"}</span></div>}
    {task.scan_progress && <div className="notice" role="status"><h2>{task.state === 'PAUSED' ? 'Scan paused' : task.state === 'CANCELLED' ? 'Scan cancelled' : task.scan_progress.phase === 'discover' ? 'Discovering files across your source folders' : 'Checking document contents'}</h2><p>{task.scan_progress.scanned} files discovered · {task.scan_progress.extracted} document contents checked · {task.scan_progress.cache_hits} cached · {task.scan_progress.matched} matches so far</p><p>{task.scan_progress.remaining} known items queued. Counts can grow as more folders are discovered. Copying starts after the scan finishes.</p></div>}
    {task.error && <div className="notice error-notice"><b>{task.state === 'REVIEW' ? 'Check the result before continuing' : 'This intent needs help'}</b><p>{task.error}</p>{task.state === 'BLOCKED' && task.pending && <button disabled={busy} onClick={() => control('skip')}>Skip this action and replan</button>}</div>}
    {(task.state === 'APPROVAL' || task.state === 'REVIEW') && pending && <div className="approval-card"><div className="eyebrow"><Icon name="shield" size={16}/> {task.state === 'APPROVAL' ? 'YOUR PERMISSION IS NEEDED' : 'UNCONFIRMED SIDE EFFECT'}</div><h2>{pending.summary}</h2><code className="tool-name">{pending.tool}</code><pre>{JSON.stringify(pending.arguments, null, 2)}</pre>{task.state === 'APPROVAL' ? <div className="button-row"><button className="primary" disabled={busy} onClick={() => control('approve', { action_id: pending.id })}>Approve this action</button><button disabled={busy} onClick={() => control('deny', { action_id: pending.id })}>Deny</button></div> : <><label className="folder-check"><input type="checkbox" checked={risk} onChange={e => setRisk(e.target.checked)}/>I checked the destination. Retrying could duplicate this action.</label><div className="button-row"><button disabled={busy || !risk} onClick={() => control('retry', { action_id: pending.id, acknowledge_duplicate_risk: true })}>Retry exact action</button><button disabled={busy} onClick={() => control('skip')}>Skip and replan</button></div></>}</div>}
    {task.state === 'WAITING_INPUT' && <form className="notice" onSubmit={e => { e.preventDefault(); control('reply', { text: reply }); }}><h2>A detail before I continue</h2><p>{task.question}</p><label className="sr-only" htmlFor="reply">Your reply</label><textarea id="reply" value={reply} onChange={e => setReply(e.target.value)} placeholder="Your answer…" maxLength={12000}/><button className="primary" disabled={busy || !reply.trim()}>Continue intent</button></form>}
    {task.answer && <div className="answer-card"><div className="eyebrow"><span className="live-dot"/> RESULT</div><div className="answer">{task.answer}</div></div>}
    <div className="section-title"><h2>Execution trail</h2><span>DURABLE CHECKPOINTS</span></div>
    <div className="steps">{task.steps.map((step, index) => <div className="step" key={step.id}><span className="step-number">✓</span><div className="step-body"><span className="step-time">{time(step.completed_at)}</span><h3>{step.summary}</h3><code>{step.tool}</code>{step.result?.artifact && <a className="artifact" href={`/api/artifact?intent=${task.id}&step=${step.id}`}><Icon name="file"/>{step.result.artifact.split(/[\\/]/).pop()} <span>Download ↗</span></a>}{step.result?.copied != null && <p className="collection-result">{step.result.copied} files copied · {step.result.scanned} scanned · {step.result.cache_hits} cached{step.result.truncated ? ' · PARTIAL SCAN' : ''}<br/>{step.result.folder}</p>}{step.metrics && <small>{step.metrics.provider} · {(step.metrics.latency_ms / 1000).toFixed(1)}s planning</small>}<details><summary>Inspect checkpoint {index + 1}</summary><pre>{JSON.stringify(step.result, null, 2)}</pre></details></div></div>)}{!task.steps.length && <p className="muted">Completed capability calls will appear here. Every result is saved before the next step.</p>}</div>
    <details className="audit"><summary>Process control block & audit log</summary><div className="pcb"><span>Identity <code>{task.id}</code></span><span>Read grants <code>{task.scopes.join(', ')}</code></span><span>Execution <code>{(task.elapsed_ms / 1000).toFixed(1)}s · {task.turns}/{task.max_turns} decisions</code></span><span>Granted folders <code>{task.roots.join('\n') || 'None'}</code></span></div><div className="audit-lines">{events.map(e => <div key={e.seq}><time>{time(e.timestamp)}</time><b>{e.kind}</b><span>{e.message}</span></div>)}</div></details>
  </>;
}

function KernelPanel({ snapshot, connected }) {
  const [host, setHost] = useState(null);
  useEffect(() => {
    let alive = true;
    const refresh = () => api('/system').then(value => { if (alive) setHost(value); }).catch(() => {});
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, []);
  const resources = snapshot?.resources;
  const tasks = snapshot?.intents || [];
  const done = tasks.filter(t => t.state === 'COMPLETED').length;
  return <aside className="kernel-panel"><div className="kernel-title"><h2><Icon name="activity" size={17}/> Kernel pulse</h2><span className="live-label"><span className={'live-dot ' + (connected ? '' : 'offline')}/>{connected ? 'LIVE' : 'OFFLINE'}</span></div><p className="kernel-subtitle">The system behind your goals.</p>
    <div className="kernel-orbit"><div className="orbit outer"/><div className="orbit inner"/><div className={'core ' + (resources?.active ? 'working' : '')}><Icon name="spark" size={28}/></div><span className="orbit-dot one"/><span className="orbit-dot two"/><span className="orbit-dot three"/></div>
    <div className="kernel-status">{resources?.active ? 'Making things happen' : 'Ready for your next intent'}<small>{resources?.active || 0} of {resources?.workers || 3} execution slots active</small></div>
    <div className="slot-row">{Array.from({ length: resources?.workers || 3 }, (_, i) => <div className={i < resources?.active ? 'slot filled' : 'slot'} key={i}/>)}</div>
    <div className="kernel-stats"><div><b>{tasks.filter(t => !TERMINAL.includes(t.state)).length}</b><span>IN PROGRESS</span></div><div><b>{done}</b><span>COMPLETED</span></div></div>
    <div className="kernel-section"><span className="kernel-label">SCHEDULING POLICY</span><h3>{snapshot?.scheduler.policy || 'Fair queue'}</h3><p>{snapshot?.scheduler.reason || 'Waiting for an intent'}</p><span className="mini-tag">Cooperative · one call per quantum</span></div>
    <div className="kernel-section"><span className="kernel-label">RESOURCE LOCKS</span>{Object.entries(resources?.locks || {}).length ? Object.entries(resources.locks).map(([name, id]) => <div className="lock-row" key={name}><span className="live-dot"/><b>{name}</b><code>{short(id)}</code></div>) : <p className="unlocked"><Icon name="shield" size={15}/> All resources available</p>}</div>
    <div className="kernel-section"><span className="kernel-label">CONNECTED CAPABILITIES</span><div className="connection-row"><span>▧</span><b>Local files</b><span className="connection-state">Ready</span></div><div className="connection-row"><span>◎</span><b>{snapshot?.config.provider === "gemini" ? "Gemini" : "Ollama"}</b><span className="connection-state">{snapshot?.config.provider === "gemini" ? (snapshot.config.gemini_configured ? "Configured" : "Set up") : snapshot?.config.model ? "Configured" : "Set up"}</span></div><div className="connection-row"><span>G</span><b>Google</b><span className="connection-state">{snapshot?.google.connected ? 'Connected' : 'Not connected'}</span></div></div>
    <div className="kernel-section"><span className="kernel-label">HOST RESOURCES · {host?.platform || 'HOST'}</span><div className="host-metrics"><span>CPU <b>{host?.cpu_percent == null ? 'Unavailable' : `${host.cpu_percent}%`}</b></span><span>Memory <b>{host?.memory_percent == null ? 'Unavailable' : `${host.memory_percent}%`}</b></span></div><p>Measured on your computer. Scheduling applies to intent calls.</p></div>
    <div className="kernel-note"><Icon name="shield" size={17}/><p>Your intent has boundaries.<br/>Only the output permissions you grant.</p></div>
  </aside>;
}

function Connections({ snapshot, perform, busy }) {
  const [provider, setProvider] = useState(snapshot?.config.provider || 'ollama');
  const [cloudModel, setCloudModel] = useState(snapshot?.config.gemini_model || 'gemini-3.5-flash-lite');
  const [apiKey, setApiKey] = useState('');
  const [models, setModels] = useState(null);
  const [model, setModel] = useState(snapshot?.config.model || '');
  const [folders, setFolders] = useState(snapshot?.config.roots.join('\n') || '');
  const [services, setServices] = useState(['calendar']);
  const [saved, setSaved] = useState(false);
  useEffect(() => { setModels(null); api('/models?provider=' + provider).then(setModels).catch(e => setModels({ reachable: false, error: e.message })); }, [provider]);
  useEffect(() => { if (snapshot) { setModel(snapshot.config.model); setFolders(snapshot.config.roots.join('\n')); } }, [snapshot?.config.model, snapshot?.config.roots.join('\n')]);
  return <><div className="eyebrow">YOUR TOOLS, CONNECTED</div><h1>Give your intent reach.</h1><p className="lede">Local intelligence, your folders, and the services you choose.</p>
    <section className="settings-card"><h2>AI provider</h2><label className="field-title">Planning service<select value={provider} onChange={e => { setProvider(e.target.value); setSaved(false); }}><option value="gemini">Gemini · cloud planning</option><option value="ollama">Ollama · private local planning</option></select></label><p className="settings-help">File copying and exports always execute locally. Gathering with the direct workflow needs no model. Providers never switch automatically.</p></section>
    {provider === 'gemini' && <section className="settings-card"><div className="settings-title"><span className="service-icon">✧</span><div><h2>Gemini</h2><p>Your goal and needed file excerpts are sent to Google.</p></div><Badge state={snapshot?.config.gemini_configured ? 'READY' : 'BLOCKED'}/></div><label className="field-title" htmlFor="gemini-key">API key · stored in your OS credential store</label><div className="field-row"><input id="gemini-key" type="password" autoComplete="off" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={snapshot?.config.gemini_configured ? 'Key saved securely; enter only to replace' : 'Enter your Gemini API key'}/><button disabled={busy || !apiKey.trim()} onClick={() => perform(async () => { await api('/ai/key', {key: apiKey}); setApiKey(''); setModels(await api('/models?provider=gemini')); })}>Save key securely</button></div><label className="field-title" htmlFor="gemini-model">Model</label><div className="field-row"><input id="gemini-model" list="gemini-models" value={cloudModel} onChange={e => { setCloudModel(e.target.value); setSaved(false); }}/><datalist id="gemini-models">{models?.models?.filter(m => !/image|tts|live|robotics|deep-research|lyria|transcrib/i.test(m)).map(m => <option key={m} value={m}/>)}</datalist><button disabled={busy} onClick={() => perform(async () => setModels(await api('/models?provider=gemini')))}>Refresh models</button></div>{models?.error && <p className="notice error-notice">{models.error}</p>}<p className="settings-help">Flash-Lite is the default for low latency. Free-tier limits depend on your Google project; quota errors are shown explicitly. IntentOS does not enable billing. <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">Manage your key ↗</a></p></section>}
    {provider === 'ollama' && <section className="settings-card"><div className="settings-title"><span className="service-icon">◎</span><div><h2>Local intelligence</h2><p>Ollama · private inference on this computer</p></div><Badge state={models?.reachable ? 'READY' : 'BLOCKED'}/></div>
      {models && !models.reachable && <div className="notice compact"><b>Ollama is not reachable</b><p>Install Ollama, start it, and download a model that supports structured JSON. Then refresh the model list.</p><a href="https://ollama.com/download" target="_blank" rel="noreferrer">Get Ollama ↗</a><code className="command">ollama pull qwen3:4b-instruct</code><small>Example model; choose a size that fits your machine.</small></div>}
      <label className="field-title" htmlFor="model">Model</label><div className="field-row"><input id="model" list="models" value={model} onChange={e => { setModel(e.target.value); setSaved(false); }} placeholder="Select or enter an installed model name"/><datalist id="models">{models?.models?.map(m => <option key={m} value={m}/>)}</datalist><button disabled={busy} onClick={() => perform(async () => setModels(await api('/models?provider=ollama')))}>Refresh models</button></div><p className="settings-help">{models?.reachable ? `${models.models.length} installed model(s) detected.` : 'No cloud fallback. No API key required.'} Inference endpoint: {snapshot?.config.ollama_url}</p>
    </section>}
    <section className="settings-card"><div className="settings-title"><span className="service-icon"><Icon name="file"/></span><div><h2>Accessible folders</h2><p>Each new intent receives only the folders you select.</p></div></div><label className="field-title" htmlFor="folders">Absolute folder paths · one per line</label><textarea id="folders" value={folders} onChange={e => { setFolders(e.target.value); setSaved(false); }} rows={4}/><p className="settings-help">The workspace is always available. Hidden paths, credentials, and kernel state are excluded. Existing intents keep their original grants.</p><button className="primary" disabled={busy} onClick={() => perform(async () => { await api('/settings', { model, provider, gemini_model: cloudModel, roots: folders.split('\n').map(s => s.trim()).filter(Boolean) }); setSaved(true); })}>{saved ? 'Settings saved ✓' : 'Save provider and folder settings'}</button></section>
    <section className="settings-card"><div className="settings-title"><span className="service-icon google-icon">G</span><div><h2>Google workspace</h2><p>Real Calendar, Drive metadata, and Gmail sending.</p></div><Badge state={snapshot?.google.connected ? 'READY' : 'PAUSED'}/></div>
      {!snapshot?.google.configured && <div className="notice compact"><b>One-time Google configuration</b><p>Create a Web application OAuth client in Google Cloud, enable Calendar / Drive / Gmail APIs, and add this exact redirect URI:</p><code className="command">{snapshot?.google.redirect_uri}</code><p>Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the project’s .env file, then restart the backend. See README for setup.</p></div>}
      <div className="check-row">{['calendar', 'drive', 'gmail'].map(s => <label key={s}><input type="checkbox" checked={services.includes(s)} onChange={e => setServices(e.target.checked ? [...services, s] : services.filter(x => x !== s))}/>{SCOPE_NAMES[s]}</label>)}</div><div className="button-row"><button className="primary" disabled={busy || !snapshot?.google.configured || !services.length} onClick={() => perform(async () => { const result = await api('/google/connect', { services }); window.location.assign(result.url); })}>Connect selected services ↗</button>{snapshot?.google.connected && <button disabled={busy} onClick={() => perform(() => api('/google/disconnect', {}))}>Disconnect locally</button>}</div><p className="settings-help">Connected: {snapshot?.google.services.join(', ') || 'none'}. Tokens stay in your OS credential store. Disconnect removes local credentials; revoke access in your Google account to remove the grant.</p>
    </section><section className="settings-card"><div className="settings-title"><span className="service-icon">⌁</span><div><h2>Google Maps</h2><p>Real routes and travel times.</p></div><span className="mini-tag">{snapshot?.google.maps ? 'Configured' : 'API key needed'}</span></div><p className="settings-help">Enable Google Routes API and set GOOGLE_MAPS_API_KEY in .env. Maps uses a separate API key and Google Cloud billing; Google sign-in alone does not enable routes.</p></section>
  </>;
}
