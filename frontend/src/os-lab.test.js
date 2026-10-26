import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {explainStep, resultSummary} from './osLabLearning.js';

// Generate evidence with the actual teaching VM, never a second implementation.
const root=fileURLToPath(new URL('../../',import.meta.url));
const venv=fileURLToPath(new URL(process.platform==='win32'?'../../.venv/Scripts/python.exe':'../../.venv/bin/python',import.meta.url));
const python=process.env.PYTHON||(existsSync(venv)?venv:'python');
const runs=JSON.parse(execFileSync(python,['-c',`
import json
from intent_kernel.os_lab import OSLab
runs={}
for name in ('round_robin','priority','preemption','memory_ipc'):
    lab=OSLab()
    states=[lab.reset(name,2,2)]
    while not states[-1]['done'] and not states[-1]['deadlocked']:
        states.append(lab.step())
    runs[name]=states
print(json.dumps(runs))
`],{cwd:root,encoding:'utf8',maxBuffer:8*1024*1024}));

test('every live and historical explanation matches the same recorded step',()=>{
  for(const states of Object.values(runs)) {
    const final=states.at(-1);
    for(const state of states.slice(1)) {
      const latest=explainStep(state);
      assert.deepEqual(explainStep(final,state.tick-1),latest,`${state.scenario} tick ${state.tick-1}`);
      assert.ok(latest.title&&latest.what&&latest.why);
      assert.doesNotMatch(JSON.stringify(latest),/undefined|NaN/);
    }
  }
});

test('narration explains preemption, turn expiry and actual I/O wake time',()=>{
  assert.match(explainStep(runs.preemption[2]).why,/P3.*higher priority.*P1/s);
  assert.match(explainStep(runs.preemption[4]).what,/ready again at tick 7/);
  assert.match(explainStep(runs.round_robin[3]).why,/P1 used its 2-tick turn/);
  assert.match(explainStep(runs.priority[3]).why,/highest ready priority/);
});

test('memory loads, IPC and the intentional fault have distinct explanations',()=>{
  const end=runs.memory_ipc.at(-1);
  const titles=end.timeline.map(row=>explainStep(end,row.tick));
  assert.ok(titles.some(s=>s.title==='P2 is waiting for a message.'));
  assert.ok(titles.some(s=>s.title==='P1 sent 42 to P2.'));
  assert.ok(titles.some(s=>s.title==='P2 received 42.'));
  assert.ok(titles.some(s=>s.concept.startsWith('Page fault')&&s.why.includes('Memory was full')));
  const fault=titles.find(s=>s.concept==='Memory protection');
  assert.match(fault.what,/address 99/);
  assert.match(fault.why,/Other tasks.*continue/);
  assert.match(resultSummary(end).text,/2 finished, 1 stopped/);
});

const bundle=await build({
  stdin:{contents:`export {default as React} from 'react'; export {default as TestRenderer} from 'react-test-renderer'; export {default as OSLab} from './OSLab.jsx';`,resolveDir:fileURLToPath(new URL('.',import.meta.url)),loader:'jsx'},
  bundle:true,platform:'node',format:'esm',write:false,loader:{'.css':'empty'},define:{'process.env.NODE_ENV':'"development"'},
  plugins:[{name:'local-lab-api',setup(builder){builder.onLoad({filter:/[\\/]api\.js$/},()=>({contents:'export const api=(...args)=>globalThis.__labApi(...args);',loader:'js'}));}}],
});
const {React,TestRenderer,OSLab}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const {act}=TestRenderer;
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const text=node=>typeof node==='string'?node:Array.isArray(node)?node.map(text).join(''):node?.children?.map(text).join('')||'';
const buttons=renderer=>renderer.root.findAllByType('button');
const button=(renderer,label)=>buttons(renderer).find(b=>text(b)===label);
function mount(initial=runs.round_robin[0]) {
  const calls=[];
  globalThis.__labApi=async(path,body)=>{calls.push([path,body]);return initial;};
  let renderer;
  act(()=>{renderer=TestRenderer.create(React.createElement(OSLab,{snapshot:{config:{scheduling:'adaptive'}},perform:fn=>fn(),busy:false}));});
  return {renderer,calls};
}

test('intro teaches lifecycle without making any task or service calls',async()=>{
  const {renderer,calls}=mount();await settle();
  assert.deepEqual(calls.map(c=>c[0]),['/os-lab']);
  assert.ok(renderer.root.findAllByType('details').find(n=>n.props.className.includes('lab-advanced')).props.open!==true);
  for(let i=0;i<5;i++) act(()=>button(renderer,'Next idea →').props.onClick());
  assert.match(text(renderer.toJSON()),/uncertain send/);
  assert.equal(calls.length,1);
  assert.ok(button(renderer,'Next step →'));
  act(()=>renderer.unmount());
});

test('lesson selection resets exactly once and waits for the server before changing lessons',async()=>{
  const {renderer,calls}=mount();await settle();
  let resolve;
  globalThis.__labApi=(path,body)=>{calls.push([path,body]);return new Promise(r=>{resolve=r;});};
  const target=buttons(renderer).find(b=>b.props.className?.includes('lab-lesson')&&text(b).includes('Share memory'));
  act(()=>{target.props.onClick();target.props.onClick();});
  assert.equal(calls.length,2);
  assert.deepEqual(calls[1],['/os-lab/reset',{scenario:'memory_ipc',quantum:2,frames:2}]);
  assert.equal(button(renderer,'Next step →').props.disabled,true);
  assert.doesNotMatch(text(renderer.toJSON()),/A small desk for memory/);
  resolve(runs.memory_ipc[0]);await settle();
  assert.match(text(renderer.toJSON()),/A small desk for memory/);
  act(()=>renderer.unmount());
});

test('changed or invalid settings cannot accidentally run the previous setup',async()=>{
  const {renderer,calls}=mount();await settle();
  const input=renderer.root.findByProps({'aria-label':'Steps in one turn'});
  act(()=>input.props.onChange({target:{value:'0'}}));
  assert.equal(button(renderer,'Next step →').props.disabled,true);
  assert.equal(button(renderer,'Apply settings & restart').props.disabled,true);
  act(()=>input.props.onChange({target:{value:'3'}}));
  globalThis.__labApi=async(path,body)=>{calls.push([path,body]);return {...runs.round_robin[0],quantum:3};};
  act(()=>button(renderer,'Apply settings & restart').props.onClick());await settle();
  assert.equal(calls.at(-1)[1].quantum,3);
  assert.equal(button(renderer,'Next step →').props.disabled,false);
  act(()=>renderer.unmount());
});

test('timeline review explains past events without executing or rewinding the simulator',async()=>{
  const {renderer,calls}=mount(runs.preemption.at(-1));await settle();
  act(()=>renderer.root.findByProps({'aria-label':'Explain step 2: P3'}).props.onClick());
  assert.match(text(renderer.toJSON()),/Reviewing step 2/);
  assert.match(text(renderer.toJSON()),/P1 saved its place/);
  assert.equal(calls.length,1);
  assert.equal(button(renderer,'Next step →').props.disabled,true);
  act(()=>button(renderer,'Back to latest step').props.onClick());
  assert.doesNotMatch(text(renderer.toJSON()),/Reviewing step 2/);
  act(()=>renderer.unmount());
});

test('errors leave a usable retry and do not mark an unfinished run complete',async()=>{
  const {renderer}=mount();await settle();
  globalThis.__labApi=async()=>{throw Error('Runtime unavailable');};
  act(()=>{button(renderer,'Next step →').props.onClick();});await settle();
  assert.match(text(renderer.toJSON()),/Runtime unavailable/);
  assert.equal(button(renderer,'Next step →').props.disabled,false);
  assert.doesNotMatch(text(renderer.toJSON()),/All three tasks finished/);
  act(()=>renderer.unmount());
});

test('auto-play uses one request at a time and pause cancels the next step',async()=>{
  const {renderer,calls}=mount();await settle();
  const originalSet=globalThis.setTimeout, originalClear=globalThis.clearTimeout;
  const timers=new Map();let sequence=0;
  globalThis.setTimeout=(callback)=>{timers.set(++sequence,callback);return sequence;};
  globalThis.clearTimeout=id=>timers.delete(id);
  globalThis.__labApi=async(path,body)=>{calls.push([path,body]);return runs.round_robin[1];};
  try {
    act(()=>button(renderer,'Auto-play').props.onClick());
    assert.equal(timers.size,1);
    const [id,tick]=[...timers][0];timers.delete(id);
    act(()=>{tick();});await settle();
    assert.equal(calls.filter(c=>c[0]==='/os-lab/step').length,1);
    assert.equal(timers.size,1);
    act(()=>button(renderer,'Pause').props.onClick());
    assert.equal(timers.size,0);
    act(()=>renderer.unmount());
  } finally {globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;}
});
