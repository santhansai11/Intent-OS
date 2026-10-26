import React, {useEffect, useRef, useState} from 'react';
import {api} from './api';
import {LESSONS, GOAL_STORY, TERMS, priorityLabel, stateLabel, instructionText, explainStep, resultSummary} from './osLabLearning';
import './os-lab.css';

function GoalWalkthrough() {
  const [index, setIndex] = useState(0);
  const step = GOAL_STORY[index];
  return <details className="lab-card lab-goal-tour" open>
    <summary>Start here: how a goal becomes a process <span className="lab-summary-note">A guided example from your project</span></summary>
    <p className="lab-caption">“Prepare for my 4 PM meeting.” Follow this example to see what the intent kernel does. This walkthrough does not run a task or access your accounts.</p>
    <div className="lab-journey" aria-label="Goal lifecycle walkthrough">{GOAL_STORY.map((s,i)=><button key={s.title} aria-pressed={i===index} onClick={()=>setIndex(i)}><span>{i+1}</span>{s.title}</button>)}</div>
    <div className="lab-story" aria-live="polite"><small>{step.concept}</small><h3>{step.title}</h3><p>{step.text}</p><blockquote>{step.example}</blockquote></div>
    <div className="lab-story-nav"><button disabled={index===0} onClick={()=>setIndex(i=>i-1)}>Previous</button><span>{index+1} of {GOAL_STORY.length}</span><button onClick={()=>setIndex(i=>(i+1)%GOAL_STORY.length)}>{index===GOAL_STORY.length-1?'Read again':'Next idea →'}</button></div>
  </details>;
}

function MemoryBoard({lab, selected}) {
  const process=lab.processes.find(p=>p.id===selected);
  return <div className="lab-card lab-memory">
    <div className="lab-card-title"><h2>A small desk for memory</h2><span>{lab.frames.filter(Boolean).length} of {lab.frames.length} slots in use</span></div>
    <p className="lab-caption">Think of memory as a desk. Each slot holds one task’s block of data. When the desk fills up, the block unused for longest is saved and moved out. A page fault means loading a block, not crashing.</p>
    <div className="lab-frames">{lab.frames.map((frame,i)=><div className={'lab-frame '+(frame?.pid||'')} key={i}><small>MEMORY SLOT {i+1}</small><b>{frame?`${frame.pid} · block ${frame.page}`:'Empty slot'}</b><span>{frame?'Data: '+frame.data.join(', '):'Available for a task'}</span></div>)}</div>
    <div className="lab-memory-counts"><span><b>{lab.metrics.page_faults}</b> block loads</span><span><b>{lab.metrics.evictions}</b> replacements</span><span><b>{lab.memory.resident_bytes}</b> bytes on the desk</span></div>
    <details><summary>See the technical memory view</summary><p className="lab-caption">A block is a 4-byte page; a slot is a frame. Each task has 16 private virtual bytes (addresses 0–15). Backing storage is a separate in-memory teaching model, not your computer’s disk.</p><p>{selected} page table: {Object.entries(process?.page_table||{}).map(([page,frame])=>`page ${page} → frame ${frame}`).join(', ')||'No blocks currently loaded'}.</p><p>Private backing storage: {lab.memory.backing_bytes} bytes. Frames and backing pages are released when a task exits.</p></details>
  </div>;
}

function AdvancedView({lab, selected, setSelected}) {
  const process=lab.processes.find(p=>p.id===selected);
  return <details className="lab-card lab-advanced">
    <summary>Under the hood <span className="lab-summary-note">Registers, process records and event log</span></summary>
    <p className="lab-caption">PC is the next instruction index. ACC is the working number. Ready wait counts time waiting for the CPU; blocked time counts time waiting for a device or message. All durations are simulated ticks.</p>
    <div className="lab-table-scroll"><table><caption>Process control blocks — current state</caption><thead><tr>{['Task','Priority','State','PC','ACC','CPU ticks','Ready wait','Blocked','First response','Turnaround'].map(h=><th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>{lab.processes.map(p=><tr key={p.id} className={p.id===selected?'lab-selected':''}><th scope="row"><button className={p.id} aria-pressed={selected===p.id} onClick={()=>setSelected(p.id)}>{p.id}</button></th><td>{priorityLabel(p.priority)}</td><td>{p.state}</td><td>{p.pc}</td><td>{p.acc}</td><td>{p.cpu_ticks}</td><td>{p.wait_ticks}</td><td>{p.blocked_ticks}</td><td>{p.response??'—'}</td><td>{p.completed_at===null?'—':p.completed_at-p.arrival}</td></tr>)}</tbody></table></div>
    {process&&<div className="lab-program-wrap"><h3>{selected} instruction list</h3><ol className="lab-program" start="0">{process.program.map((ins,i)=><li key={i} className={i===process.pc?'current':''}><code>{ins.join(' ')}</code><span>{instructionText(ins)}{i===process.pc?' ← next':''}</span></li>)}</ol>{process.error&&<p className="lab-fault">{process.error}</p>}</div>}
    <h3>Recorded events <small>Newest first</small></h3><div className="lab-events">{[...lab.events].reverse().map(event=><div className="lab-event" key={event.seq}><code>t={event.tick}</code><b>{event.pid||'CPU'}</b><span><strong>{event.kind.replaceAll('_',' ')}</strong> {event.message}{event.registers&&<small>PC {event.registers.pc} · ACC {event.registers.acc}</small>}</span></div>)}</div>
  </details>;
}

export default function OSLab({snapshot, perform, busy}) {
  const [lab,setLab]=useState(null), [error,setError]=useState(''), [loading,setLoading]=useState(true);
  const [playing,setPlaying]=useState(false), [working,setWorking]=useState(false);
  const [quantum,setQuantum]=useState(2), [frames,setFrames]=useState(3), [speed,setSpeed]=useState(1400);
  const [selected,setSelected]=useState('P1'), [inspectedTick,setInspectedTick]=useState(null);
  const inFlight=useRef(false), mounted=useRef(false), generation=useRef(0), timeline=useRef(null);
  useEffect(()=>{
    mounted.current=true;
    const version=++generation.current;
    api('/os-lab').then(s=>{if(mounted.current&&generation.current===version){setLab(s);setQuantum(s.quantum);setFrames(s.frames.length);setLoading(false);}})
      .catch(e=>{if(mounted.current&&generation.current===version){setError(e.message);setLoading(false);}});
    return()=>{mounted.current=false;generation.current++;};
  },[]);

  async function request(path,body) {
    if(inFlight.current) return;
    inFlight.current=true;setWorking(true);
    const version=++generation.current;
    try {
      const next=await api(path,body);
      if(!mounted.current||generation.current!==version)return;
      setLab(next);setError('');setInspectedTick(null);
      if(path.endsWith('/reset')){setQuantum(next.quantum);setFrames(next.frames.length);setSelected('P1');}
      if(next.done||next.deadlocked)setPlaying(false);
    } catch(e) {if(mounted.current&&generation.current===version){setError(e.message);setPlaying(false);}}
    finally {inFlight.current=false;if(mounted.current&&generation.current===version){setWorking(false);setLoading(false);}}
  }
  const dirty=!!lab&&(Number(quantum)!==lab.quantum||Number(frames)!==lab.frames.length);
  const valid=[quantum,frames].every(value=>Number.isInteger(Number(value))&&Number(value)>=1&&Number(value)<=8);
  const canStep=!!lab&&!working&&!loading&&!dirty&&!lab.done&&!lab.deadlocked;
  useEffect(()=>{if(timeline.current&&inspectedTick===null)timeline.current.scrollLeft=timeline.current.scrollWidth;},[lab?.tick,inspectedTick]);
  useEffect(()=>{
    if(!playing||!canStep)return;
    const timer=setTimeout(()=>request('/os-lab/step',{}),speed);
    return()=>clearTimeout(timer);
  },[playing,lab,speed,working,loading,dirty]);

  function reset(scenario=lab?.scenario||'round_robin', custom=false) {
    if(inFlight.current||loading||(custom&&!valid))return;
    setPlaying(false);
    request('/os-lab/reset',{scenario,quantum:custom?Number(quantum):lab?.quantum||2,frames:custom?Number(frames):lab?.frames.length||3});
  }
  function download() {
    const url=URL.createObjectURL(new Blob([JSON.stringify(lab,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download=`intent-os-${lab.scenario}-tick-${lab.tick}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  const lesson=LESSONS[lab?.scenario]||LESSONS.round_robin;
  const explanation=explainStep(lab,inspectedTick??lab?.timeline.at(-1)?.tick);
  const historical=inspectedTick!==null&&inspectedTick!==lab?.timeline.at(-1)?.tick;
  const result=lab&&(lab.done||lab.deadlocked)?resultSummary(lab):null;
  return <section className="os-lab" aria-label="OS learning lab">
    <div className="eyebrow">OS LAB / LEARN BY DOING</div>
    <div className="lab-heading"><div><h1>One step. One clear idea.</h1><p className="lede">See how a computer shares work, protects resources and remembers progress. No OS knowledge needed.</p></div><span className="lab-chip">SAFE PRACTICE SPACE</span></div>
    <div className="lab-principles"><span><b>Schedule</b> Who works next?</span><span><b>Protect</b> What can it access?</span><span><b>Recover</b> Where can it resume?</span></div>
    <GoalWalkthrough/>
    <div className="lab-section-heading"><div><small>YOUR NEXT STEP</small><h2>Pick a hands-on lesson</h2></div><span>New here? Start with 01.</span></div>
    <div className="lab-lessons">{Object.entries(LESSONS).map(([key,item])=><button key={key} className={'lab-lesson '+(lab?.scenario===key?'active':'')} aria-pressed={lab?.scenario===key} disabled={working||loading} onClick={()=>reset(key)}><span>{item.number}{key==='round_robin'&&<small>START HERE</small>}</span><b>{item.title}</b><p>{item.intro}</p><small>{lab?.scenario===key?'Loaded · click to restart':'Load lesson →'}</small></button>)}</div>
    <p className="lab-caption">Lessons use three example tasks, P1, P2 and P3. Choosing a lesson starts a fresh practice run. The lab state is shared across tabs; it does not send emails, read your files or create intents.</p>
    {loading&&<p role="status" className="lab-loading">Getting the practice space ready…</p>}
    {error&&<p className="error-banner" role="alert">{error} {!lab&&'Choose a lesson above to try loading again.'}</p>}
    {lab&&<>
      <div className="lab-card lab-stage">
        <div className="lab-card-title"><div><small>LESSON {lesson.number} · {lesson.concept}</small><h2>{lesson.title}</h2></div><span className="lab-run-status">{result?'Run ended':playing?'Playing':working?'Updating…':'Paused'} · {lab.tick} steps recorded</span></div>
        <p className="lab-caption">{lesson.watch}</p>
        <div className="lab-transport"><button className="primary" disabled={!canStep||playing} onClick={()=>request('/os-lab/step',{})}>Next step →</button><button disabled={!playing&&!canStep} onClick={()=>{setInspectedTick(null);setPlaying(value=>!value);}}>{playing?'Pause':'Auto-play'}</button><button disabled={working} onClick={()=>reset()}>Restart lesson</button><label>Animation speed<select aria-label="Animation speed" value={speed} onChange={event=>setSpeed(Number(event.target.value))}><option value={2200}>Slow</option><option value={1400}>Normal</option><option value={500}>Fast</option></select></label></div>
        {dirty&&<p className="lab-settings-notice" role="status">You changed the experiment settings. Apply them below to restart, or keep the current settings.</p>}
        <div className="lab-narration" aria-live={playing?'off':'polite'} aria-atomic="true"><div className="lab-narration-top"><span>{historical?`Reviewing step ${inspectedTick+1}`:lab.tick?`What happened in step ${lab.tick}`:'Before you begin'}</span><small>{explanation.concept}</small></div><h3>{explanation.title}</h3><p>{explanation.what}</p><div className="lab-why"><b>Why?</b><p>{explanation.why}</p></div>{historical&&<button onClick={()=>setInspectedTick(null)}>Back to latest step</button>}</div>
        <div className="lab-section-heading compact"><h3>Where are the tasks now?</h3><small>Current state after {lab.tick} steps{historical?' · not the earlier step above':''}</small></div>
        <div className="lab-processes">{lab.processes.map(process=><button key={process.id} className={'lab-process '+process.id+(selected===process.id?' selected':'')} aria-pressed={selected===process.id} onClick={()=>setSelected(process.id)}><div><b>{process.id}</b><small>{priorityLabel(process.priority)} priority</small></div><strong>{stateLabel(process)}</strong><progress max={process.program.length} value={process.pc} aria-label={`${process.id} completed instructions`}/><span>{process.pc} of {process.program.length} instructions finished</span><small>{process.state==='FAILED'?'Invalid address stopped this task':instructionText(process.program[process.pc])}</small></button>)}</div>
        <div className="lab-queue"><b>Waiting for the CPU</b>{lab.ready.map(id=><span className={id} key={id}>{id}</span>)}{!lab.ready.length&&<span>None right now</span>}<small>High priority first; equal priorities take turns.</small></div>
        {result&&<div className="lab-result" role="status"><h3>{result.title}</h3><p>{result.text}</p><p><b>Try next:</b> {lesson.try}</p></div>}
        <details className="lab-experiment"><summary>Try a different setup <span className="lab-summary-note">Turn length{lab.scenario==='memory_ipc'?' and memory capacity':''}</span></summary><p className="lab-caption">{lesson.try} Applying settings starts this lesson over.</p><div className="lab-controls"><label>Steps in one turn (quantum)<input aria-label="Steps in one turn" type="number" min="1" max="8" value={quantum} disabled={playing||working} onChange={event=>setQuantum(event.target.value)}/><small>1–8 simulated ticks; this does not change animation speed.</small></label>{lab.scenario==='memory_ipc'&&<label>Memory slots (frames)<input aria-label="Memory slots" type="number" min="1" max="8" value={frames} disabled={playing||working} onChange={event=>setFrames(event.target.value)}/><small>Each slot holds one 4-byte block.</small></label>}<button disabled={playing||working||!valid} onClick={()=>reset(lab.scenario,true)}>Apply settings & restart</button>{dirty&&<button disabled={working} onClick={()=>{setQuantum(lab.quantum);setFrames(lab.frames.length);}}>Keep current settings</button>}</div>{!valid&&<p role="alert">Choose a whole number from 1 to 8.</p>}</details>
      </div>
      <div className="lab-card"><div className="lab-card-title"><h2>The story so far</h2><span>Click any step to read its explanation</span></div><div className="lab-timeline" ref={timeline} aria-label="Recorded CPU steps">{lab.timeline.map(row=><button className={'lab-tick '+(row.pid||'idle')} key={row.tick} aria-label={`Explain step ${row.tick+1}: ${row.pid||'CPU idle'}`} aria-pressed={(inspectedTick??lab.timeline.at(-1)?.tick)===row.tick} onClick={()=>{setPlaying(false);setInspectedTick(row.tick);}}><small>STEP {row.tick+1}</small><b>{row.pid||'Idle'}</b><span>{row.operation==='PAGE FAULT'?'Load memory':row.operation==='IDLE'?'Waiting':row.operation==='IO'?'Wait for device':row.operation==='RECV'?'Receive':row.operation==='SEND'?'Send':row.operation==='ADD'?'Calculate':row.operation==='READ'?'Read memory':'Write memory'}</span></button>)}{!lab.timeline.length&&<p className="lab-caption">Press Next step to see the first decision. One step is one simulated tick, not one second.</p>}</div></div>
      {lab.scenario==='memory_ipc'&&<MemoryBoard lab={lab} selected={selected}/>}
      <div className="lab-connection"><small>HOW THIS CONNECTS TO INTENTOS</small><p>{lesson.connection}</p><p>Here, instructions run on a teaching CPU. Your real goals run through the intent kernel above Windows or Linux.</p></div>
      <AdvancedView lab={lab} selected={selected} setSelected={setSelected}/>
      <div className="lab-export"><span>Need evidence for your review? Export the actual recorded steps and events.</span><button disabled={working} onClick={download}>Download run data (.json)</button></div>
    </>}
    <details className="lab-card lab-glossary"><summary>A little help with the words <span className="lab-summary-note">Plain-language glossary</span></summary><dl>{TERMS.map(([term,meaning])=><div key={term}><dt>{term}</dt><dd>{meaning}</dd></div>)}</dl></details>
    <details className="lab-card lab-real-settings"><summary>Advanced: change scheduling for real intents</summary><p className="lab-caption">These buttons change your actual workspace, not this lesson. Current mode: <b>{snapshot?.config?.scheduling||'unknown'}</b>. Strict priority disables aging and deadline overrides and can leave lower-priority work waiting. Both modes switch at safe model/tool boundaries. Active calls finish normally.</p><div className="button-row"><button disabled={busy||!snapshot||!perform} onClick={()=>perform(()=>api('/settings',{scheduling:'strict_priority'}))}>Use strict priority for real intents</button><button disabled={busy||!snapshot||!perform} onClick={()=>perform(()=>api('/settings',{scheduling:'adaptive'}))}>Use adaptive scheduling for real intents</button></div></details>
  </section>;
}
