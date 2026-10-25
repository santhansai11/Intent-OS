import React, {useEffect, useRef, useState} from 'react';
import {api} from './api';
import './os-lab.css';

const scenarios = {
  priority: ['Three priorities', 'All arrive at tick 0. P2 (high) completes, then P3 (medium), then P1 (low). Quantum expiry alone never lets a lower priority bypass a ready higher priority.'],
  preemption: ['Arrivals & I/O', 'P1 starts at tick 0. P3 arrives at 1 and preempts it. P2 arrives at 2 and preempts P3. When P2 waits for I/O, P3 runs; P2 returns at tick 7 and preempts again.'],
  round_robin: ['Equal-priority rotation', 'All three have medium priority. Each receives at most one quantum before going to the back of its ready queue. Registers resume from the saved context.'],
  memory_ipc: ['Paging & messages', 'P2 waits for a message from P1. Private pages share limited physical frames using LRU replacement. P1 deliberately accesses address 99 to demonstrate an isolated protection fault.'],
};
const priorityName = p => p === 'NORMAL' ? 'MEDIUM' : p;

export default function OSLab({snapshot, perform, busy}) {
  const [lab, setLab] = useState(null), [error, setError] = useState('');
  const [playing, setPlaying] = useState(false), [working, setWorking] = useState(false);
  const [scenario, setScenario] = useState('preemption'), [quantum, setQuantum] = useState(2), [frames, setFrames] = useState(3);
  const [speed, setSpeed] = useState(650), [selected, setSelected] = useState('P2');
  const inFlight = useRef(false);
  useEffect(() => { api('/os-lab').then(s=>{setLab(s);setScenario(s.scenario);setQuantum(s.quantum);setFrames(s.frames.length);}).catch(e=>setError(e.message)); }, []);
  async function step() {
    if(inFlight.current) return;
    inFlight.current=true; setWorking(true);
    try { const s=await api('/os-lab/step',{});setLab(s);if(s.done||s.deadlocked)setPlaying(false);setError(''); }
    catch(e) {setError(e.message);setPlaying(false);}
    finally {inFlight.current=false;setWorking(false);}
  }
  useEffect(()=>{if(!playing||!lab||lab.done||lab.deadlocked)return;const timer=setTimeout(step,speed);return()=>clearTimeout(timer);},[playing,lab,speed]);
  async function reset() {
    setPlaying(false);setWorking(true);inFlight.current=true;
    try {setLab(await api('/os-lab/reset',{scenario,quantum:Number(quantum),frames:Number(frames)}));setError('');}
    catch(e){setError(e.message);}
    finally{setWorking(false);inFlight.current=false;}
  }
  function download() {
    const url=URL.createObjectURL(new Blob([JSON.stringify(lab,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download=`intent-os-${lab.scenario}-tick-${lab.tick}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  const p=lab?.processes.find(p=>p.id===selected);
  return <section className="os-lab">
    <div className="eyebrow">KERNEL / INTERACTIVE LAB</div>
    <div className="lab-heading"><div><h1>Watch the scheduler work.</h1><p className="lede">An executable virtual CPU. Every decision, register and memory access is inspectable.</p></div><span className="lab-chip">VIRTUAL TIME · SINGLE CPU</span></div>
    <p className="lab-boundary">Lab ticks are instruction units, not milliseconds. These programs run in an isolated teaching VM; Windows schedules the host app. Real intents use cooperative call boundaries.</p>
    {error&&<p className="error-banner" role="alert">{error}</p>}
    <div className="lab-controls">
      <label>Scenario<select aria-label="Lab scenario" value={scenario} onChange={e=>setScenario(e.target.value)} disabled={playing||working}>{Object.entries(scenarios).map(([k,[v]])=><option key={k} value={k}>{v}</option>)}</select></label>
      <label>Quantum (ticks)<input aria-label="Quantum in ticks" type="number" min="1" max="8" value={quantum} onChange={e=>setQuantum(e.target.value)} disabled={playing||working}/></label>
      <label>Physical frames<input aria-label="Physical frames" type="number" min="1" max="8" value={frames} onChange={e=>setFrames(e.target.value)} disabled={playing||working}/></label>
      <button onClick={reset} disabled={working}>Load / reset</button>
    </div>
    {lab&&<>
      <div className="lab-transport"><button className="primary" disabled={lab.done||lab.deadlocked} onClick={()=>setPlaying(!playing)}>{playing?'Pause playback':'Play demonstration'}</button><button disabled={playing||working||lab.done||lab.deadlocked} onClick={step}>Step one tick</button><label>Playback<select aria-label="Playback speed" value={speed} onChange={e=>setSpeed(Number(e.target.value))}><option value={1200}>Slow</option><option value={650}>Normal</option><option value={150}>Fast</option></select></label><button onClick={download}>Export trace</button><span role="status">{lab.done?'Run complete':lab.deadlocked?'Blocked: no process can wake a receiver':playing?'Executing':'Paused'} · {scenarios[lab.scenario][0]}</span></div>
      <p className="lab-explanation">{scenarios[lab.scenario][1]}</p>
      <div className="lab-metrics"><div><small>CLOCK</small><b>{lab.tick}<em> ticks</em></b></div><div><small>CPU OWNER</small><b>{lab.current||'Idle'}</b></div><div><small>SLICE USED</small><b>{lab.slice_used}<em> / {lab.quantum}</em></b></div><div><small>CONTEXT SWITCHES</small><b>{lab.metrics.context_switches}</b></div><div><small>PAGE FAULTS</small><b>{lab.metrics.page_faults}</b></div></div>
      <div className="lab-card"><div className="lab-card-title"><h2>CPU timeline</h2><span>One cell = one executed tick</span></div><div className="lab-timeline" aria-label="CPU execution timeline">{lab.timeline.length?lab.timeline.map(t=><div className={'lab-tick '+(t.pid||'idle')} key={t.tick} title={`Tick ${t.tick}: ${t.pid||'Idle'} · ${t.operation}; PC ${t.before?.pc??'—'} → ${t.after?.pc??'—'}`}><small>{t.tick}</small><b>{t.pid||'—'}</b><span>{t.operation}</span></div>):<p className="lede">Press Step or Play to execute the first instruction.</p>}</div><div className="lab-queue"><b>Ready queue</b>{lab.ready.map(id=><span className={id} key={id}>{id}</span>)}{!lab.ready.length&&<span>Empty</span>}<small>Highest priority first · FIFO among equals</small></div></div>
      <div className="lab-card"><div className="lab-card-title"><h2>Process control blocks</h2><span>Select a process to inspect its instructions</span></div><div className="lab-table-scroll"><table><thead><tr>{['Process','Priority','State','PC','ACC','CPU','Ready wait','Blocked','Response','Turnaround'].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{lab.processes.map(p=><tr key={p.id} className={selected===p.id?'lab-selected':''}><td><button className={'lab-pid '+p.id} onClick={()=>setSelected(p.id)}>{p.id}</button></td><td>{priorityName(p.priority)}</td><td>{p.state}</td><td>{p.pc}</td><td>{p.acc}</td><td>{p.cpu_ticks}</td><td>{p.wait_ticks}</td><td>{p.blocked_ticks}</td><td>{p.response??'—'}</td><td>{p.completed_at===null?'—':p.completed_at-p.arrival}</td></tr>)}</tbody></table></div></div>
      <div className="lab-columns"><div className="lab-card"><div className="lab-card-title"><h2>Physical memory</h2><span>{lab.memory.resident_bytes} / {lab.memory.capacity_bytes} bytes</span></div><div className="lab-frames">{lab.frames.map((f,i)=><div className={'lab-frame '+(f?.pid||'')} key={i}><small>FRAME {i} · {i*4}–{i*4+3}</small><b>{f?`${f.pid} / page ${f.page}`:'Free'}</b><code>{f?f.data.join(' · '):'0 · 0 · 0 · 0'}</code></div>)}</div><p className="lede">4-byte pages · private 16-byte address space per process · {lab.metrics.evictions} LRU evictions. Page-in costs one tick; the instruction retries. Frames and backing pages are released on exit.</p><p>Backing store allocated: <b>{lab.memory.backing_bytes} bytes</b></p>{p&&<p><b>{p.id} page table: </b>{Object.entries(p.page_table).map(([v,f])=>`page ${v} → frame ${f}`).join(', ')||'No resident pages'}</p>}</div>
      <div className="lab-card"><div className="lab-card-title"><h2>{selected} instructions</h2><span>Saved PC {p?.pc} · ACC {p?.acc}</span></div><ol className="lab-program" start="0">{p?.program.map((ins,i)=><li key={i} className={i===p.pc?'current':''}><code>{ins.join(' ')}</code>{i===p.pc&&<span>← next instruction</span>}</li>)}</ol>{p?.error&&<p role="status" className="lab-fault">{p.error}</p>}<p className="lede">A blocked receive keeps its PC. I/O yields the CPU. Each dispatch restores PC and ACC from the saved process context.</p></div></div>
      <div className="lab-card"><div className="lab-card-title"><h2>Scheduling & memory audit</h2><span>{lab.events.length} events · newest first</span></div><div className="lab-events">{[...lab.events].reverse().map(e=><div className="lab-event" key={e.seq}><code>t={e.tick}</code><b>{e.pid||'CPU'}</b><span><strong>{e.kind.replaceAll('_',' ')}</strong> {e.message}{e.registers&&<small>PC {e.registers.pc} · ACC {e.registers.acc}</small>}</span></div>)}</div></div>
    </>}
    <details className="lab-card"><summary>Apply strict priority to real intents</summary><p>Current mode: <b>{snapshot?.config.scheduling||'adaptive'}</b>. Strict priority checks the highest runnable priority at every model/tool boundary, with round robin among equals. Aging and deadline overrides are disabled. It cannot interrupt an in-flight API call; a low-priority intent can starve while higher-priority work stays ready. Multiple execution slots may run concurrently.</p><div className="button-row"><button disabled={busy} onClick={()=>perform(()=>api('/settings',{scheduling:'strict_priority'}))}>Use strict priority</button><button disabled={busy} onClick={()=>perform(()=>api('/settings',{scheduling:'adaptive'}))}>Use adaptive scheduling</button></div></details>
  </section>;
}
