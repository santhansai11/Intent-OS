import React, { useEffect, useRef, useState } from 'react';
import { api, uploadFile } from './api';
import { sourceFolders } from './composer.js';
import Connections from './Connections';
import Datasets from './Datasets';
import { Icon, Badge, SCOPE_NAMES } from './ui';

const DONE = ['COMPLETED', 'CANCELLED', 'FAILED'];
const ATTENTION = ['BLOCKED', 'REVIEW', 'APPROVAL', 'WAITING_INPUT'];
const date = n => new Date(n * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
const basename = path => path?.split(/[\\/]/).pop();
const presets = [
  ['file', 'Draft from a reference', 'Use my reference attachment as the structure for a report. Use my source attachments for factual content. Mark missing evidence clearly.'],
  ['spark', 'Ask my knowledge', 'Search my indexed documents and answer this question with source citations: '],
  ['grid', 'Compare assessments', 'Read all assessments in the selected folder. Compare their objectives, methods, code and results, and identify missing assessments.'],
  ['clock', 'Prepare for a meeting', 'Find my next calendar meeting, search relevant Drive files and emails, and prepare a briefing with sources and action items.'],
  ['activity', 'Extract action items', 'Read my attachments and extract action items, owners and deadlines. Clearly label details that are not specified.'],
];

export default function App() {
  const [snapshot, setSnapshot] = useState(null), [online, setOnline] = useState(false);
  const [page, setPage] = useState('workspace'), [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [goal, setGoal] = useState(''), [attachments, setAttachments] = useState([]);
  const [roots, setRoots] = useState(null), [options, setOptions] = useState(false);
  const [output, setOutput] = useState(''), [format, setFormat] = useState(''), [filename, setFilename] = useState('');
  const [access, setAccess] = useState('selected'), [scopes, setScopes] = useState(['files','web']);
  const [priority, setPriority] = useState('NORMAL'), [deadline, setDeadline] = useState('');
  const [autoOutputs, setAutoOutputs] = useState(true), [mode, setMode] = useState('agent');
  const [dependencies, setDependencies] = useState([]), [inspector, setInspector] = useState(false);
  const [theme, setTheme] = useState(() => localStorage.getItem('intent-theme') || 'light');
  const [deleteIds, setDeleteIds] = useState(null), [deleteUploads, setDeleteUploads] = useState(false);
  const [drag, setDrag] = useState(false), [notice, setNotice] = useState('');
  const fileInput = useRef(null);
  const tasks = snapshot?.intents || [], task = tasks.find(t => t.id === selected);
  const selectedRoots = sourceFolders(snapshot?.config, roots);
  const active = tasks.filter(t => !DONE.includes(t.state));
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('intent-theme', theme); }, [theme]);
  useEffect(() => { window.scrollTo(0, 0); }, [page, selected]);
  useEffect(() => {
    api('/status').then(setSnapshot).catch(e => setError(e.message));
    const stream = new EventSource('/api/events');
    stream.addEventListener('snapshot', e => { setSnapshot(JSON.parse(e.data)); setOnline(true); });
    stream.onerror = () => setOnline(false);
    return () => stream.close();
  }, []);
  async function perform(fn) {
    setBusy(true); setError('');
    try { const result = await fn(); setSnapshot(await api('/status')); return result; }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  function open(t) { setSelected(t.id); setPage('workspace'); }
  function newIntent() { setSelected(null); setPage('workspace'); }
  const control = (action, data={}) => perform(() => api(`/intents/${selected}/${action}`, data));
  async function addFiles(files) {
    if (files.length + attachments.length > 12) { setError('Attach up to 12 files per intent.'); return; }
    await perform(async () => {
      for (const file of files) {
        setNotice(`Uploading ${file.name}…`);
        const uploaded = await uploadFile(file);
        setAttachments(old => [...old, {...uploaded, role: 'source'}]);
      }
      setNotice('Files ready. Choose Reference for a draft or template you want to follow.');
    });
  }
  function submit(e) {
    e.preventDefault();
    if (busy || !goal.trim() || !snapshot) return;
    perform(async () => {
      const folder = output.trim() || snapshot.config.workspace;
      const target = filename.trim() ? (/^(?:[a-z]:[\\/]|[\\/])/i.test(filename) ? filename.trim() : `${folder}/${filename.trim()}`) : '';
      const collection = target || `${folder}/collection-${Date.now()}`;
      const text = mode === 'collect' ? `Gather files about ${goal} into ${collection}. Preserve originals.` : goal + (format ? `\nSave the result as ${format.toUpperCase()}${target ? ` at ${target}` : ` in ${folder}`}.` : target ? `\nSave the result at ${target}.` : '');
      const result = await api('/intents', {text, roots: [...new Set([...selectedRoots, snapshot.config.workspace])], search_roots: selectedRoots,
        output_folder: folder, access_mode: access, scopes: ['system', ...scopes], auto_outputs: autoOutputs,
        priority, deadline: deadline ? new Date(deadline).toISOString() : null,
        attachments: attachments.map(a => ({id: a.id, role: a.role})), depends_on: dependencies,
        ...(mode === 'collect' ? {workflow: {type: 'collect', query: goal, destination: collection}} : {})});
      setGoal(''); setAttachments([]); setDependencies([]); setNotice(''); open(result);
    });
  }
  const nav = [['workspace','grid','Workspace'],['processes','activity','Processes'],['knowledge','spark','Knowledge'],['history','clock','History'],['connections','plug','Connections']];
  return <div className="shell">
    <aside className="sidebar">
      <button className="brand" onClick={newIntent}><span className="brand-symbol"><Icon name="spark" size={26}/></span><span>intent<span className="brand-os">OS</span><small>A WORKSPACE THAT ACTS</small></span></button>
      <button className="new-intent" onClick={newIntent}><Icon name="plus"/> New intent <kbd>↗</kbd></button>
      <div className="nav-label">YOUR WORKSPACE</div>
      <nav>{nav.map(([id,icon,title]) => <button key={id} className={'nav '+(page===id?'active':'')} onClick={()=>setPage(id)}><Icon name={icon}/>{title}{id==='processes'&&<span className="count">{active.length}</span>}</button>)}</nav>
      <div className="nav-label recent-label">PINNED & RECENT</div>
      <div className="recent-list">{[...tasks].sort((a,b)=>Number(!!b.pinned)-Number(!!a.pinned)).slice(0,7).map(t=><button key={t.id} className={'recent '+(selected===t.id?'chosen':'')} onClick={()=>open(t)}><span className={'status-dot state-'+t.state}/><span>{t.pinned?'★ ':''}{t.goal.split('\n')[0]}</span></button>)}</div>
      <div className="sidebar-bottom"><span className={'live-dot '+(!online?'offline':'')}/><div>{online?'Connected locally':'Reconnecting'}<small>{active.length} active · {tasks.filter(t=>t.state==='COMPLETED').length} completed</small></div><span className="version">v3</span></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumbs">Personal workspace <span>/</span><b>{nav.find(n=>n[0]===page)?.[2]}</b></div><div className="topbar-right"><span className="local-pill"><span className="live-dot"/> Local-first</span><button className="icon-button" onClick={()=>setTheme(theme==='light'?'dark':'light')} aria-label="Toggle color theme">{theme==='light'?'☾':'☀'}</button><button className={'icon-button '+(inspector?'selected':'')} onClick={()=>setInspector(!inspector)} aria-label="Toggle runtime details"><Icon name="activity"/></button><span className="avatar">S</span></div></header>
      {error&&<div className="error-banner" role="alert">{error}<button onClick={()=>setError('')} aria-label="Dismiss error">×</button></div>}
      <div className={'workspace-layout '+(inspector?'with-inspector':'')}>
        <main className="content">
          {page==='connections'?<Connections snapshot={snapshot} perform={perform} busy={busy}/>:
           page==='history'?<History tasks={tasks} open={open} busy={busy} requestDelete={ids=>{setDeleteIds(ids);setDeleteUploads(false);}}/>:
           page==='knowledge'?<Knowledge snapshot={snapshot} perform={perform} busy={busy} open={open}/>:
           page==='processes'?<Processes snapshot={snapshot} open={open} perform={perform} busy={busy}/>:
           task?<IntentDetail task={task} control={control} busy={busy} events={(snapshot?.events||[]).filter(e=>e.intent_id===task.id)} onDelete={()=>setDeleteIds([task.id])} onNew={newIntent}/>:
           <>
            <div className="welcome"><div className="eyebrow"><span className="tiny-line"/> YOUR NEXT CHAPTER</div><h1>Less managing.<br/><span>More making progress.</span></h1><p className="lede">Bring your files and an idea. Give the next step a place to happen.</p><div className="welcome-art" aria-hidden="true"><div className="art-ring one"/><div className="art-ring two"/><div className="art-core"><Icon name="spark" size={35}/></div><span className="art-dot"/></div></div>
            <form className={'composer '+(drag?'dragging':'')} onSubmit={submit} onDragOver={e=>{e.preventDefault();setDrag(true);}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);if(!busy)addFiles([...e.dataTransfer.files]);}}>
              <div className="composer-top"><span className="mini-tag"><span className="live-dot"/> {mode==='collect'?'File collection':'Ready for your intent'}</span><select aria-label="Workflow" value={mode} onChange={e=>setMode(e.target.value)}><option value="agent">Ask anything</option><option value="collect">Collect files</option></select></div>
              <label className="sr-only" htmlFor="goal">What would you like to get done?</label><textarea id="goal" value={goal} onChange={e=>setGoal(e.target.value)} placeholder="Describe what you want to get done…" maxLength={12000} onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))submit(e);}}/>
              {attachments.length>0&&<div className="attachment-list">{attachments.map(a=><div className="attachment" key={a.id}><span className="file-tile"><Icon name="file"/></span><div><b title={a.name}>{a.name}</b><small>{(a.bytes/1024).toFixed(0)} KB · uploaded locally</small></div><select aria-label={`Role for ${a.name}`} value={a.role} onChange={e=>setAttachments(old=>old.map(x=>x.id===a.id?{...x,role:e.target.value}:x))}><option value="source">Source</option><option value="reference">Reference</option></select><button type="button" disabled={busy} aria-label={`Remove ${a.name}`} onClick={()=>perform(async()=>{await api('/uploads/remove',{id:a.id});setAttachments(old=>old.filter(x=>x.id!==a.id));})}>×</button></div>)}</div>}
              {notice&&<p className="upload-notice" role="status">{notice}</p>}
              {options&&<div className="intent-options">
                <div className="field-row"><label>Search in<select value={access} onChange={e=>setAccess(e.target.value)}><option value="selected">Selected folders</option><option value="system">Accessible drives</option></select></label><label>Priority<select value={priority} onChange={e=>setPriority(e.target.value)}>{['LOW','NORMAL','HIGH'].map(p=><option key={p}>{p}</option>)}</select></label><label>Deadline<input type="datetime-local" value={deadline} onChange={e=>setDeadline(e.target.value)}/></label></div>
                {access==='selected'&&<div className="folder-options">{snapshot?.config.roots.map(r=><label className="folder-check" key={r}><input type="checkbox" checked={selectedRoots.includes(r)} onChange={e=>setRoots(e.target.checked?[...selectedRoots,r]:selectedRoots.filter(x=>x!==r))}/><span>{r}</span></label>)}<button type="button" className="text-button" onClick={()=>setPage('connections')}>Manage folders →</button></div>}
                <div className="field-row"><label>Save in folder<input value={output} onChange={e=>setOutput(e.target.value)} placeholder={snapshot?.config.workspace}/></label><label>Format<select value={format} onChange={e=>setFormat(e.target.value)}><option value="">Use my request</option>{['pdf','docx','pptx','xlsx','txt','md','html','csv','json','zip'].map(f=><option key={f}>{f}</option>)}</select></label></div>
                <label>Output name<input value={filename} onChange={e=>setFilename(e.target.value)} placeholder="Optional filename or collection folder"/></label>
                <div className="check-row">{Object.entries(SCOPE_NAMES).map(([k,v])=><label key={k}><input type="checkbox" checked={scopes.includes(k)} onChange={e=>setScopes(e.target.checked?[...scopes,k]:scopes.filter(s=>s!==k))}/>{v}</label>)}</div>
                <label className="folder-check"><input type="checkbox" checked={autoOutputs} onChange={e=>setAutoOutputs(e.target.checked)}/>Allow new reports and collections</label>
                <label>Start after these intents complete<select multiple value={dependencies} onChange={e=>setDependencies([...e.target.selectedOptions].map(o=>o.value))}>{tasks.filter(t=>!['CANCELLED','FAILED'].includes(t.state)).slice(0,30).map(t=><option key={t.id} value={t.id}>{t.goal.slice(0,75)}</option>)}</select></label>
              </div>}
              <div className="composer-bottom"><div className="composer-actions"><input ref={fileInput} type="file" multiple hidden accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv,.json,.png,.jpg,.jpeg,.webp" onChange={e=>{addFiles([...e.target.files]);e.target.value='';}}/><button className="attach-button" type="button" disabled={busy} onClick={()=>fileInput.current?.click()}><Icon name="plus" size={17}/> Attach files</button><button type="button" className={'text-button '+(options?'selected':'')} onClick={()=>setOptions(!options)}>Options <span>{options?'⌃':'⌄'}</span></button></div><button className="run-button" disabled={busy||!goal.trim()||!snapshot} aria-label="Run intent"><span>{busy?'Working…':'Start intent'}</span><Icon name="arrow" size={17}/></button></div>
            </form>
            <div className="composer-caption"><span>{snapshot?.config.provider==='gemini'?'Gemini':'Local Ollama'} · {attachments.length?`${attachments.length} attachments`:`${selectedRoots.length} source folders`}</span><span>PDF, documents & images · Ctrl + Enter</span></div>
            <div className="section-title"><h2>A starting point</h2><span>MAKE IT YOURS</span></div><div className="workflow-grid">{presets.map(([icon,title,text])=><button key={title} onClick={()=>{setGoal(text);if(title==='Prepare for a meeting')setScopes(['files','web','calendar','gmail','drive']);document.getElementById('goal')?.focus();}}><Icon name={icon}/><b>{title}</b><span>↗</span></button>)}</div>
            <div className="section-title"><h2>Recent activity</h2><button className="text-button" onClick={()=>setPage('history')}>All history →</button></div><TaskRows tasks={tasks.slice(0,4)} open={open}/>
           </>}
          <footer>INTENTOS <span>Your work, with context.</span><span className="footer-end">LOCAL-FIRST WORKSPACE</span></footer>
        </main>
        {inspector&&<RuntimePanel snapshot={snapshot} online={online}/>}
      </div>
    </div>
    {deleteIds&&<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="delete-title"><div className="eyebrow">HISTORY</div><h2 id="delete-title">Delete {deleteIds.length} intent{deleteIds.length===1?'':'s'}?</h2><p>This removes their history and audit logs. Original files, generated reports, sent emails and calendar events stay where they are.</p><label className="folder-check"><input type="checkbox" checked={deleteUploads} onChange={e=>setDeleteUploads(e.target.checked)}/>Also remove uploaded copies used only by these intents</label><div className="button-row"><button onClick={()=>setDeleteIds(null)} disabled={busy}>Keep history</button><button className="danger" disabled={busy} onClick={()=>perform(async()=>{await api('/history/delete',{ids:deleteIds,remove_uploads:deleteUploads});if(deleteIds.includes(selected))setSelected(null);setDeleteIds(null);})}>Delete history</button></div></section></div>}
  </div>;
}

function TaskRows({tasks,open}) {
  return <div className="activity-list">{tasks.length?tasks.map(t=><button className="activity-row" key={t.id} onClick={()=>open(t)}><span className={'activity-icon '+(t.state==='COMPLETED'?'done':'')}><Icon name={t.state==='COMPLETED'?'shield':'activity'}/></span><span className="activity-text"><b>{t.goal.split('\n')[0]}</b><small>{date(t.created_at)} · {t.steps.length} steps</small></span><Badge state={t.state}/><Icon name="chevron" size={14}/></button>):<div className="empty"><Icon name="spark" size={28}/><h3>A fresh start.</h3><p>Your work will appear here when you start an intent.</p></div>}</div>;
}

function Answer({text}) {
  const blocks = [], lines = text.split('\n');
  const inline = value => value.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part,i)=>part.startsWith('**')?<strong key={i}>{part.slice(2,-2)}</strong>:part.startsWith('`')?<code key={i}>{part.slice(1,-1)}</code>:part);
  for(let i=0;i<lines.length;i++) {
    const line=lines[i];
    if(line.startsWith('```')) { const code=[]; while(++i<lines.length&&!lines[i].startsWith('```'))code.push(lines[i]); blocks.push(<pre key={i}>{code.join('\n')}</pre>); }
    else if(/^#{1,6}\s/.test(line)) { const level=Math.min(4,line.match(/^#+/)[0].length+1);blocks.push(React.createElement(`h${level}`,{key:i},inline(line.replace(/^#+\s/,'')))); }
    else if(/^\s*(?:[-*]|\d+\.)\s/.test(line)) { const items=[];const ordered=/^\s*\d+\./.test(line);while(i<lines.length&&/^\s*(?:[-*]|\d+\.)\s/.test(lines[i])){items.push(<li key={i}>{inline(lines[i].replace(/^\s*(?:[-*]|\d+\.)\s/,''))}</li>);i++;}i--;blocks.push(React.createElement(ordered?'ol':'ul',{key:i},items)); }
    else if(line.trim()) blocks.push(<p key={i}>{inline(line)}</p>);
  }
  return <div className="answer formatted-answer">{blocks}</div>;
}

function IntentDetail({task,control,busy,events,onDelete,onNew}) {
  const [reply,setReply]=useState(''), [risk,setRisk]=useState(false), [tab,setTab]=useState('result');
  const pending=task.pending;
  const sources=task.steps.flatMap(s=>['knowledge_search','dataset_search'].includes(s.tool)?(s.result.matches||[]):s.tool==='files_read_many'?(s.result.documents||[]):['files_read','files_ocr'].includes(s.tool)?[s.result]:[]);
  const graph=[...task.steps.map(s=>({...s,done:true})),...(pending?[pending]:[])];
  return <>
    <button className="text-button back-link" onClick={onNew}>← Workspace</button>
    <div className="detail-heading"><div className="eyebrow">INTENT / {task.id.slice(0,8)}</div><Badge state={task.state}/></div>
    <h1 className="task-title">{task.goal.split('\n')[0]}</h1><div className="task-meta"><span>{date(task.created_at)}</span><span>{task.priority.toLowerCase()} priority</span><span>{task.steps.length} completed steps</span></div>
    <div className="task-controls"><button disabled={busy} onClick={()=>control('pin',{pinned:!task.pinned})}>{task.pinned?'★ Pinned':'☆ Pin intent'}</button>{['READY','RUNNING','RECOVERY'].includes(task.state)&&<button disabled={busy} onClick={()=>control('pause')}>Pause</button>}{['BLOCKED','PAUSED'].includes(task.state)&&<button disabled={busy} onClick={()=>control('resume')}>Resume</button>}{!DONE.includes(task.state)&&task.state!=='REVIEW'&&<button disabled={busy} onClick={()=>control('cancel')}>Cancel</button>}{DONE.includes(task.state)&&<button className="text-button" disabled={busy} onClick={onDelete}>Delete history</button>}</div>
    {task.waiting_for?.length>0&&<div className="notice">Waiting for {task.waiting_for.length} prerequisite intent(s) to complete.</div>}
    {task.active&&<div className="running-bar"><span className="spinner"/>{task.active==='Planning next action'?'Planning the next step…':task.active.replaceAll('_',' ')}<span>Progress is saved</span></div>}
    {task.scan_progress&&<div className="progress-card"><div><b>{task.pending?.tool==='knowledge_index'?'Building knowledge':'Searching files'}</b><span>{task.scan_progress.scanned} discovered · {task.scan_progress.extracted} read · {task.scan_progress.cache_hits} cached</span></div><div className="indeterminate"/></div>}
    {task.error&&<div className="notice error-notice"><h3>{task.state==='REVIEW'?'Check the destination before retrying':'This intent needs attention'}</h3><p>{task.error}</p>{task.state==='BLOCKED'&&<button disabled={busy} onClick={()=>control('skip')}>Skip and replan</button>}</div>}
    {pending&&['APPROVAL','REVIEW'].includes(task.state)&&<div className="approval-card"><div className="eyebrow">{task.state==='REVIEW'?'UNCONFIRMED ACTION':'ACTION PREVIEW'}</div><h3>{pending.summary}</h3><pre>{JSON.stringify(pending.arguments,null,2)}</pre>{task.state==='APPROVAL'?<div className="button-row"><button className="primary" disabled={busy} onClick={()=>control('approve',{action_id:pending.id})}>Approve action</button><button disabled={busy} onClick={()=>control('deny',{action_id:pending.id})}>Decline</button></div>:<><label className="folder-check"><input type="checkbox" checked={risk} onChange={e=>setRisk(e.target.checked)}/>I checked the destination; retrying may duplicate the action.</label><button disabled={busy||!risk} onClick={()=>control('retry',{action_id:pending.id,acknowledge_duplicate_risk:true})}>Retry exact action</button><button disabled={busy} onClick={()=>control('skip')}>Skip</button></>}</div>}
    {task.state==='WAITING_INPUT'&&<form className="notice" onSubmit={e=>{e.preventDefault();control('reply',{text:reply});}}><h3>{task.question}</h3><textarea aria-label="Your reply" value={reply} onChange={e=>setReply(e.target.value)}/><button className="primary" disabled={busy||!reply.trim()}>Continue</button></form>}
    <div className="detail-tabs" role="tablist">{[['result','Result'],['workflow','Workflow'],['sources',`Sources · ${sources.length}`],['activity','Activity']].map(([id,label])=><button role="tab" aria-selected={tab===id} key={id} className={tab===id?'active':''} onClick={()=>setTab(id)}>{label}</button>)}</div>
    {tab==='result'&&<><div className="answer-card"><div className="eyebrow"><span className="live-dot"/>{task.answer?'YOUR RESULT':'IN PROGRESS'}</div>{task.answer?<Answer text={task.answer}/>:<div className="empty"><Icon name="activity"/><p>{ATTENTION.includes(task.state)?'Resolve the item above to continue.':'Your result will appear here as the intent completes.'}</p></div>}{task.steps.filter(s=>s.result?.artifact).map(s=><a key={s.id} className="artifact" href={`/api/artifact?intent=${task.id}&step=${s.id}`}><Icon name="file"/>{basename(s.result.artifact)}<span>Download ↗</span></a>)}</div><Contract contract={task.contract}/></>}
    {tab==='workflow'&&<><div className="section-title"><h2>From intent to outcome</h2><span>ACTUAL EXECUTION</span></div><div className="workflow-path"><div className="flow-node complete"><span>◉</span><b>Your intent</b><small>{task.attachments?.length||0} attachments · {task.scopes.length} read grants</small></div>{graph.map((s,i)=><React.Fragment key={s.id}><div className="flow-connector"/><div className={'flow-node '+(s.done?'complete':'current')}><span>{s.done?'✓':i+1}</span><b>{s.summary}</b><small>{s.tool.replaceAll('_',' ')}{s.tool==='files_read_many'?' · parallel file reads':''}</small>{s.result?.documents&&<div className="parallel-branches">{s.result.documents.map(r=><span key={r.path}>{r.error?'!':'✓'} {basename(r.path)}</span>)}</div>}</div></React.Fragment>)}<div className="flow-connector"/><div className={'flow-node '+(task.state==='COMPLETED'?'complete':'')}><span>◇</span><b>Validate & complete</b><small>Required sources, output length and citation checks</small></div></div></>}
    {tab==='sources'&&<><div className="section-title"><h2>Evidence behind this intent</h2><span>READ-ONLY SOURCES</span></div>{task.attachments?.map(a=><div className="source-card" key={a.id}><Icon name="file"/><div><b>{a.name}</b><small>{a.role==='reference'?'Reference structure':'Source material'} · {(a.bytes/1024).toFixed(0)} KB</small></div></div>)}{sources.map((r,i)=><details className="source-evidence" key={r.source_id||`${r.path}-${i}`}><summary><span className="citation">{r.citation||i+1}</span><b>{r.name||basename(r.path)}</b><span>{r.error?'Unreadable':r.ocr?'OCR':r.truncated?'Partial':'Read'}</span></summary><small>{r.path||r.record_id}</small>{r.coverage&&<p>{r.coverage}</p>}<pre>{r.excerpt||r.content||r.error}</pre></details>)}{!sources.length&&<div className="empty">Read and retrieved sources will appear here.</div>}</>}
    {tab==='activity'&&<><div className="steps">{task.steps.map(s=><details className="step" key={s.id}><summary><span className="step-number">✓</span><b>{s.summary}</b><small>{s.metrics?`${(s.metrics.latency_ms/1000).toFixed(1)}s planning`:''}</small></summary><pre>{JSON.stringify(s.result,null,2)}</pre></details>)}</div><details className="audit"><summary>Technical audit log</summary><div className="pcb"><span>ID <code>{task.id}</code></span><span>Grants <code>{task.scopes.join(', ')}</code></span><span>Execution <code>{(task.elapsed_ms/1000).toFixed(1)}s · {task.turns}/{task.max_turns} decisions</code></span></div>{events.map(e=><div className="audit-line" key={e.seq}><small>{date(e.timestamp)}</small><b>{e.kind}</b><span>{e.message}</span></div>)}</details></>}
  </>;
}

function Contract({contract:c}) {
  if(!c)return null;
  return <div className="contract-strip"><span><Icon name="shield" size={16}/> Completion checks</span>{c.required_attachments>0&&<span>{c.read_attachments}/{c.required_attachments} attachments read</span>}{c.minimum_nonempty_lines>0&&<span>≥ {c.minimum_nonempty_lines} content lines</span>}{c.available_assessments.length>0&&<span>{c.remaining_assessment_documents.length===0?'All listed assessments read':`${c.remaining_assessment_documents.length} assessment(s) remaining`}</span>}{c.citations_available>0&&<span>{c.citations_available} retrieved citations</span>}{!c.required_attachments&&!c.minimum_nonempty_lines&&!c.available_assessments.length&&!c.citations_available&&<span>Scoped permissions enforced</span>}</div>;
}

function History({tasks,open,requestDelete,busy}) {
  const [query,setQuery]=useState(''),[filter,setFilter]=useState('all'),[checked,setChecked]=useState([]);
  const visible=tasks.filter(t=>(filter==='all'||t.state===filter)&&t.goal.toLowerCase().includes(query.toLowerCase()));
  useEffect(()=>setChecked(old=>old.filter(id=>tasks.some(t=>t.id===id))),[tasks]);
  return <><div className="eyebrow">YOUR TRAIL OF WORK</div><h1>History</h1><p className="lede">Find a result. Pick up a thread. Make space for what’s next.</p><div className="history-toolbar"><input type="search" aria-label="Search history" placeholder="Search your intents…" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="Filter history" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All states</option>{DONE.map(s=><option key={s}>{s}</option>)}</select><button disabled={busy||!checked.length} onClick={()=>requestDelete(checked)}>Delete {checked.length||''} selected</button><button className="text-button" disabled={busy||!tasks.some(t=>DONE.includes(t.state))} onClick={()=>requestDelete(tasks.filter(t=>DONE.includes(t.state)).map(t=>t.id))}>Clear completed history</button></div><div className="history-table">{visible.map(t=><div className="history-row" key={t.id}><input type="checkbox" aria-label={`Select ${t.goal}`} disabled={!DONE.includes(t.state)} checked={checked.includes(t.id)} onChange={e=>setChecked(e.target.checked?[...checked,t.id]:checked.filter(i=>i!==t.id))}/><button onClick={()=>open(t)}><b>{t.pinned?'★ ':''}{t.goal.split('\n')[0]}</b><small>{date(t.created_at)} · {t.steps.length} steps</small></button><Badge state={t.state}/></div>)}{!visible.length&&<div className="empty">No intents match this view.</div>}</div></>;
}

function Processes({snapshot,open,perform,busy}) {
  const [execution,setExecution]=useState(snapshot?.config.execution||{workers:3,model_slots:1,read_slots:2,adaptive:true});
  const tasks=snapshot?.intents||[], active=tasks.filter(t=>!DONE.includes(t.state));
  return <><div className="eyebrow">WORK IN MOTION</div><h1>Process studio</h1><p className="lede">Independent work can run together. Dependent work waits its turn.</p><div className="metric-grid"><div><small>ACTIVE INTENTS</small><b>{active.length}</b></div><div><small>EXECUTING NOW</small><b>{snapshot?.resources.active||0}<em> / {snapshot?.resources.workers||3}</em></b></div><div><small>COMPLETED</small><b>{tasks.filter(t=>t.state==='COMPLETED').length}</b></div></div><div className="settings-card execution-settings"><h2>Execution capacity</h2><div className="field-row">{[['workers','Total slots'],['model_slots','AI planning slots'],['read_slots','File read slots']].map(([k,label])=><label key={k}>{label}<input type="number" min="1" max="8" value={execution[k]} onChange={e=>setExecution({...execution,[k]:Number(e.target.value)})}/></label>)}</div><div className="button-row"><label className="folder-check"><input type="checkbox" checked={execution.adaptive} onChange={e=>setExecution({...execution,adaptive:e.target.checked})}/>Reduce concurrency above 90% memory use</label><button disabled={busy} onClick={()=>perform(()=>api('/settings',{execution}))}>Save limits</button></div>{snapshot?.resources.memory_throttled&&<p className="notice">Memory pressure detected. New work is limited to one execution slot.</p>}</div><div className="section-title"><h2>Live processes</h2><span>{snapshot?.scheduler.policy}</span></div>{active.map(t=><div className="process-card" key={t.id}><div><Badge state={t.state}/><small>{t.waiting_for?.length?`Waiting for ${t.waiting_for.length} dependencies`:t.active||'Waiting for next step'}</small></div><button className="process-goal" onClick={()=>open(t)}>{t.goal.split('\n')[0]}</button><div className="process-bottom"><span>{t.steps.length} completed steps</span><select aria-label={`Priority for ${t.id}`} value={t.priority} disabled={busy} onChange={e=>perform(()=>api(`/intents/${t.id}/priority`,{priority:e.target.value}))}>{['LOW','NORMAL','HIGH'].map(p=><option key={p}>{p}</option>)}</select><button onClick={()=>open(t)}>Inspect →</button></div>{t.depends_on?.length>0&&<div className="dependency-links">{t.depends_on.map(id=><span key={id}>↳ {(tasks.find(x=>x.id===id)?.goal||id).slice(0,70)}</span>)}</div>}</div>)}{!active.length&&<div className="empty"><Icon name="activity" size={28}/><h3>Everything is caught up.</h3><p>Start an intent to see its execution here.</p></div>}</>;
}

function Knowledge({snapshot,perform,busy,open}) {
  const [status,setStatus]=useState(null),[query,setQuery]=useState(''),[result,setResult]=useState(null),[folder,setFolder]=useState(''),[embedding,setEmbedding]=useState(snapshot?.config.embedding_model||'');
  useEffect(()=>{api('/knowledge').then(setStatus).catch(()=>{});},[snapshot?.revision]);
  const selectedFolder=folder||sourceFolders(snapshot?.config,null)[0]||'';
  return <><div className="eyebrow">CONTEXT THAT STAYS WITH YOU</div><h1>Your knowledge,<br/><span className="accent">connected.</span></h1><p className="lede">Turn selected documents into searchable evidence. Find passages, then ask with context.</p><div className="metric-grid"><div><small>DOCUMENTS</small><b>{status?.documents||0}</b></div><div><small>PASSAGES</small><b>{status?.chunks||0}</b></div><div><small>LOCAL VECTORS</small><b>{status?.embedded_chunks||0}</b></div></div><div className="knowledge-search"><Icon name="spark"/><form onSubmit={e=>{e.preventDefault();perform(async()=>setResult(await api('/knowledge/search',{query,roots:[selectedFolder]})));}}><input aria-label="Search knowledge" value={query} onChange={e=>setQuery(e.target.value)} placeholder="What do your documents say about…?"/><button className="primary" disabled={busy||!query.trim()||!selectedFolder}>Search passages →</button></form></div><div className="index-controls"><label>Source folder<select value={selectedFolder} onChange={e=>setFolder(e.target.value)}>{snapshot?.config.roots.map(r=><option key={r}>{r}</option>)}</select></label><button disabled={busy||!selectedFolder} onClick={()=>perform(async()=>{const t=await api('/intents',{text:`Update the local knowledge index for ${selectedFolder}`,roots:[selectedFolder],search_roots:[selectedFolder],scopes:['system','files'],workflow:{type:'index',path:selectedFolder}});open(t);})}>Build / refresh index</button></div><details className="settings-card"><summary>Retrieval settings</summary><p>Keyword search works without a model. Add an installed local embedding model to enable semantic search and rank fusion. Document text stays on this computer during indexing.</p><div className="field-row"><input aria-label="Local embedding model" value={embedding} onChange={e=>setEmbedding(e.target.value)} placeholder="nomic-embed-text"/><button disabled={busy} onClick={()=>perform(()=>api('/settings',{embedding_model:embedding}))}>Save model</button></div><small>Refresh existing indexes after changing the model. Nested code projects and tool folders are excluded.</small></details>{result&&<><div className="section-title"><h2>{result.matches.length} retrieved passages</h2><span>{result.latency_ms} ms</span></div><p className="retrieval-label">{result.retrieval}{result.stale_files_excluded?` · ${result.stale_files_excluded} changed files need reindexing`:''}</p>{result.warning&&<p className="notice">{result.warning} Keyword results are shown.</p>}{result.matches.map(r=><article className="retrieval-card" key={r.source_id}><div><span className="citation">{r.citation}</span><b>{r.name}</b><small>Passage {r.chunk}</small></div><p>{r.excerpt}</p><details><summary>Source & coverage</summary><small>{r.path}</small><p>{r.coverage}</p></details></article>)}{!result.matches.length&&<div className="empty">No indexed matches. Build the index for this folder, or try a different question.</div>}</>}<Datasets perform={perform} busy={busy} open={open}/></>;
}

function RuntimePanel({snapshot,online}) {
  const [host,setHost]=useState(null);
  useEffect(()=>{let alive=true;const refresh=()=>api('/system').then(v=>{if(alive)setHost(v);}).catch(()=>{});refresh();const timer=setInterval(refresh,5000);return()=>{alive=false;clearInterval(timer);};},[]);
  return <aside className="kernel-panel"><div className="kernel-title"><h2>Runtime</h2><span className="mini-tag">{online?'LIVE':'OFFLINE'}</span></div><div className="runtime-symbol"><Icon name="spark" size={34}/></div><h3>{snapshot?.resources.active?'Work is underway':'Ready when you are'}</h3><p>{snapshot?.resources.active||0} / {snapshot?.resources.workers||3} execution slots</p><div className="kernel-section"><div className="kernel-label">SCHEDULING</div><b>{snapshot?.scheduler.policy}</b><p>{snapshot?.scheduler.reason}</p></div><div className="kernel-section"><div className="kernel-label">RESOURCE LOCKS</div>{Object.entries(snapshot?.resources.locks||{}).map(([k,v])=><div className="lock-row" key={k}><span>{k}</span><code>{v.slice(0,8)}</code></div>)}{!Object.keys(snapshot?.resources.locks||{}).length&&<p>All resources available</p>}</div><div className="kernel-section"><div className="kernel-label">YOUR COMPUTER</div><div className="host-metrics"><span>CPU <b>{host?.cpu_percent??'—'}%</b></span><span>Memory <b>{host?.memory_percent??'—'}%</b></span></div></div><div className="kernel-note"><Icon name="shield"/><p>Local file operations.<br/>Explicit access per intent.</p></div></aside>;
}
