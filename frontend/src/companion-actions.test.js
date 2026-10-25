import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

// Exercise the real JSX handlers without a browser or a live service account.
const bundle = await build({
  stdin: { contents: `export {default as React} from 'react'; export {default as TestRenderer} from 'react-test-renderer'; export {default as ActionConversation} from './ActionConversation.jsx'; export {default as CompanionChat} from './CompanionChat.jsx'; export {default as RobotCompanion} from './RobotCompanion.jsx'; export {default as useVoiceInput} from './useVoiceInput.js'; export {default as useOrbiiSpeech} from './useOrbiiSpeech.js'; export {default as OrbiiVoiceControls} from './OrbiiVoiceControls.jsx';`, resolveDir: fileURLToPath(new URL('.',import.meta.url)), loader:'jsx' },
  bundle:true,platform:'node',format:'esm',write:false,define:{'process.env.NODE_ENV':'"development"'},
});
const {React,TestRenderer,ActionConversation,CompanionChat,RobotCompanion,useVoiceInput,useOrbiiSpeech,OrbiiVoiceControls}=await import('data:text/javascript;base64,'+Buffer.from(bundle.outputFiles[0].text).toString('base64'));
const {act}=TestRenderer;
const request={id:'intent-A',state:'APPROVAL',goal:'Send the report',pending:{id:'action-1',tool:'gmail_send',summary:'Send the reviewed report.',arguments:{to:'reviewer@example.com',subject:'Report',body:'The full message\nwith a second line.',cc:['owner@example.com'],attachments:[{name:'report.pdf',path:'D:/reports/report.pdf'}]}}};
function mount(task=request,props={}) {
  const calls=[]; let renderer;
  act(()=>{renderer=TestRenderer.create(React.createElement(ActionConversation,{task,online:true,busy:false,act:(...args)=>calls.push(args),...props}));});
  return {renderer,calls};
}
const label = node => node.children.filter(value=>typeof value==='string').join('');

test('allow and deny use the displayed intent and immutable action ID',()=>{
  const {renderer,calls}=mount();
  const buttons=renderer.root.findAllByType('button');
  act(()=>buttons.find(b=>label(b)==='Allow this action').props.onClick());
  act(()=>buttons.find(b=>label(b)==='Don’t allow').props.onClick());
  assert.deepEqual(calls,[['intent-A','approve',{action_id:'action-1'}],['intent-A','deny',{action_id:'action-1'}]]);
  act(()=>renderer.unmount());
});

test('the conversational preview preserves all action arguments, including nested values',()=>{
  const {renderer}=mount();
  const content=JSON.stringify(renderer.toJSON());
  for(const text of ['reviewer@example.com','owner@example.com','Report','The full message','with a second line.','report.pdf','D:/reports/report.pdf','Recipient','Message']) assert.ok(content.includes(text),text);
  assert.equal(renderer.root.findAllByType('pre').length,0);
  act(()=>renderer.unmount());
});

test('offline and in-flight actions cannot be approved in the UI',()=>{
  for(const props of [{online:false},{busy:true}]) {
    const {renderer}=mount(request,props);
    renderer.root.findAllByType('button').forEach(button=>assert.equal(button.props.disabled,true));
    act(()=>renderer.unmount());
  }
});

test('uncertain writes require duplicate-risk acknowledgement, reset for the next action',()=>{
  const calls=[];
  const task={...request,state:'REVIEW'};
  const render=(t,key)=>React.createElement(ActionConversation,{key,task:t,online:true,busy:false,act:(...args)=>calls.push(args)});
  let renderer; act(()=>{renderer=TestRenderer.create(render(task,'action-1'));});
  const retry=()=>renderer.root.findAllByType('button').find(button=>label(button)==='Retry this action');
  assert.equal(retry().props.disabled,true);
  act(()=>renderer.root.findByType('input').props.onChange({target:{checked:true}}));
  assert.equal(retry().props.disabled,false);
  act(()=>retry().props.onClick());
  assert.deepEqual(calls,[['intent-A','retry',{action_id:'action-1',acknowledge_duplicate_risk:true}]]);
  act(()=>renderer.update(render({...task,pending:{...task.pending,id:'action-2'}},'action-2')));
  assert.equal(retry().props.disabled,true);
  act(()=>renderer.unmount());
});

test('Orbii sends a real answer to the waiting intent and rejects blank replies',()=>{
  const {renderer,calls}=mount({id:'waiting-intent',state:'WAITING_INPUT',question:'Which folder?'});
  const form=renderer.root.findByType('form');
  act(()=>form.props.onSubmit({preventDefault(){}})); assert.equal(calls.length,0);
  act(()=>renderer.root.findByType('textarea').props.onChange({target:{value:'D:/Reports'}}));
  act(()=>form.props.onSubmit({preventDefault(){}}));
  assert.deepEqual(calls,[['waiting-intent','reply',{text:'D:/Reports'}]]);
  act(()=>renderer.unmount());
});


test('chat displays the actual answer and only sends on deliberate form submission', () => {
  const calls=[]; let renderer;
  const voice={supported:true,active:false,target:null,phase:'idle',start:args=>calls.push(['voice',args]),stop:()=>{}};
  const props={task:{answer:'**A process** is a running program.'},value:'What is a thread?',onText:()=>{},onSubmit:text=>calls.push(['send',text]),voice,busy:false,online:true};
  act(()=>{renderer=TestRenderer.create(React.createElement(CompanionChat,props));});
  assert.ok(JSON.stringify(renderer.toJSON()).includes('is a running program.'));
  assert.deepEqual(calls,[]);
  act(()=>renderer.root.findAllByType('button').find(b=>b.props['aria-label']==='Use voice input').props.onClick());
  assert.equal(calls[0][0],'voice'); assert.equal(calls[0][1].target,'orbii');
  act(()=>renderer.root.findByType('form').props.onSubmit({preventDefault(){}}));
  assert.deepEqual(calls[1],['send','What is a thread?']);
  for(const update of [{voice:{...voice,active:true,target:'orbii'}},{online:false},{busy:true},{value:'   '}]) {
    act(()=>renderer.update(React.createElement(CompanionChat,{...props,...update})));
    act(()=>renderer.root.findByType('form').props.onSubmit({preventDefault(){}}));
    assert.equal(calls.length,2);
  }
  act(()=>renderer.unmount());
});


function companionEnvironment() {
  const restore=[];
  const mock=(key,value)=>{ const old=Object.getOwnPropertyDescriptor(globalThis,key); restore.push(()=>old?Object.defineProperty(globalThis,key,old):delete globalThis[key]); Object.defineProperty(globalThis,key,{configurable:true,writable:true,value}); };
  mock('localStorage',{getItem:()=>null,setItem:()=>{}});
  mock('window',{innerWidth:1440,innerHeight:900,matchMedia:()=>({matches:false,addEventListener(){},removeEventListener(){}}),addEventListener(){},removeEventListener(){}});
  mock('document',{hidden:false,documentElement:{dataset:{}},getElementById:()=>null,querySelector:()=>({}),addEventListener(){},removeEventListener(){}});
  mock('ResizeObserver',class {observe(){} disconnect(){}});
  mock('IntersectionObserver',class {observe(){} disconnect(){}});
  mock('requestAnimationFrame',()=>1); mock('cancelAnimationFrame',()=>{});
  return ()=>restore.reverse().forEach(fn=>fn());
}

test('clicking Orbii opens text chat without starting voice; explicit listening and close track session state', () => {
  const restore=companionEnvironment(); let renderer;
  try {
    const calls=[];
    const voice={supported:true,active:false,target:null,phase:'idle',start:arg=>calls.push(['start',arg.target]),cancel:()=>calls.push(['cancel']),stop(){}};
    const props={tasks:[],selected:null,page:'history',draft:'',online:true,busy:false,act(){},openIntent(){},requestVersion:0,voice,onAsk(){}};
    act(()=>{renderer=TestRenderer.create(React.createElement(RobotCompanion,props),{createNodeMock:()=>({style:{},focus(){}})});});
    assert.deepEqual(calls,[]);
    act(()=>renderer.root.findByProps({className:'companion-hit'}).props.onClick());
    assert.deepEqual(calls,[['cancel']]);
    assert.equal(renderer.root.findByProps({id:'orbii-draft'}).props.readOnly,false);
    act(()=>renderer.update(React.createElement(RobotCompanion,{...props,voice:{...voice,active:true,target:'orbii',phase:'listening'}})));
    assert.ok(renderer.root.findAllByType('div').some(n=>n.props.className?.includes('stage-listening')));
    assert.equal(renderer.root.findByProps({id:'orbii-draft'}).props.readOnly,true);
    act(()=>renderer.root.findByProps({'aria-label':'Minimize Orbii conversation'}).props.onClick());
    assert.deepEqual(calls.at(-1),['cancel']);
    assert.equal(renderer.root.findAllByProps({id:'orbii-conversation'}).length,0);
  } finally { if(renderer) act(()=>renderer.unmount()); restore(); }
});

test('automatic permission conversations never start recording and keep the action review visible', () => {
  const restore=companionEnvironment(); let renderer;
  try {
    const starts=[];
    const voice={supported:true,active:false,target:null,phase:'idle',start:()=>starts.push('start'),cancel(){},stop(){}};
    act(()=>{renderer=TestRenderer.create(React.createElement(RobotCompanion,{tasks:[request],selected:null,page:'history',draft:'',online:true,busy:false,act(){},openIntent(){},requestVersion:0,voice,onAsk(){}}),{createNodeMock:()=>({style:{},focus(){}})});});
    assert.deepEqual(starts,[]);
    assert.equal(renderer.root.findAllByProps({id:'orbii-conversation'}).length,1);
    assert.ok(renderer.root.findAllByType('button').some(b=>label(b)==='Allow this action'));
    assert.equal(renderer.root.findAllByProps({id:'orbii-draft'}).length,1);
  } finally { if(renderer) act(()=>renderer.unmount()); restore(); }
});


function mountCompletionCompanion(tasks) {
  const starts=[];
  const voice={supported:true,active:false,target:null,phase:'idle',start:()=>starts.push('start'),cancel(){},stop(){}};
  const props={tasks,selected:null,page:'processes',draft:'',online:true,busy:false,act(){},openIntent(){},requestVersion:0,voice,onAsk(){}};
  let renderer;
  act(()=>{renderer=TestRenderer.create(React.createElement(RobotCompanion,props),{createNodeMock:()=>({style:{},focus(){}})});});
  return {renderer,starts,update:tasks=>act(()=>renderer.update(React.createElement(RobotCompanion,{...props,tasks})))};
}
const completionPopup = renderer => renderer.root.findAllByProps({'aria-label':'Intent finished notification'});

test('completion celebrates once and opens the real answer without recording', () => {
  const restore=companionEnvironment(); let view;
  try {
    const running={id:'answer-1',state:'RUNNING',goal:'What is a process?',created_at:1};
    view=mountCompletionCompanion([running]);
    assert.equal(completionPopup(view.renderer).length,0);
    const done={...running,state:'COMPLETED',answer:'A process is a running program.'};
    view.update([done]);
    assert.equal(completionPopup(view.renderer).length,1);
    assert.ok(view.renderer.root.findAllByType('div').some(n=>n.props.className?.includes('stage-completed')));
    assert.ok(JSON.stringify(view.renderer.toJSON()).includes('Intent finished'));
    act(()=>view.renderer.root.findAllByType('button').find(b=>label(b)==='Read answer ↗').props.onClick());
    assert.equal(completionPopup(view.renderer).length,0);
    assert.ok(JSON.stringify(view.renderer.toJSON()).includes(done.answer));
    assert.deepEqual(view.starts,[]);
    view.update([{...done}]);
    assert.equal(completionPopup(view.renderer).length,0);
    assert.ok(JSON.stringify(view.renderer.toJSON()).includes(done.answer));
  } finally { if(view) act(()=>view.renderer.unmount()); restore(); }
});

test('old completed history and failures never trigger a finished popup', () => {
  const restore=companionEnvironment(); let view;
  try {
    const old={id:'old',state:'COMPLETED',goal:'Old question',answer:'Old answer',created_at:1};
    view=mountCompletionCompanion([old,{id:'failed',state:'RUNNING',goal:'A task'}]);
    view.update([old,{id:'failed',state:'FAILED',goal:'A task'}]);
    assert.equal(completionPopup(view.renderer).length,0);
    assert.deepEqual(view.starts,[]);
  } finally { if(view) act(()=>view.renderer.unmount()); restore(); }
});

test('simultaneous completions queue and a dismissed result remains available', () => {
  const restore=companionEnvironment(); let view;
  try {
    const tasks=['one','two'].map(id=>({id,state:'RUNNING',goal:id,created_at:1}));
    view=mountCompletionCompanion(tasks);
    const done=tasks.map(t=>({...t,state:'COMPLETED',answer:'Answer for '+t.id}));
    view.update(done);
    assert.deepEqual(completionPopup(view.renderer)[0].findByType('small').children,['2',' finished']);
    act(()=>view.renderer.root.findByProps({'aria-label':'Dismiss intent finished notification'}).props.onClick());
    assert.equal(completionPopup(view.renderer).length,1);
    assert.ok(completionPopup(view.renderer)[0].findByType('p').children.includes('two'));
    act(()=>view.renderer.root.findByProps({'aria-label':'Dismiss intent finished notification'}).props.onClick());
    assert.equal(completionPopup(view.renderer).length,0);
    view.update(done.map(t=>({...t})));
    assert.equal(completionPopup(view.renderer).length,0);
    act(()=>view.renderer.root.findByProps({className:'companion-hit'}).props.onClick());
    assert.ok(JSON.stringify(view.renderer.toJSON()).includes('Answer for two'));
  } finally { if(view) act(()=>view.renderer.unmount()); restore(); }
});

test('reading a completed answer keeps another intent’s permission review intact', () => {
  const restore=companionEnvironment(); let view;
  try {
    const running={id:'quick-question',state:'RUNNING',goal:'Explain threads',created_at:1};
    view=mountCompletionCompanion([request,running]);
    view.update([request,{...running,state:'COMPLETED',answer:'Threads run within a process.'}]);
    act(()=>view.renderer.root.findAllByType('button').find(b=>label(b)==='Read answer ↗').props.onClick());
    assert.ok(view.renderer.root.findAllByType('button').some(b=>label(b)==='Allow this action'));
    assert.ok(JSON.stringify(view.renderer.toJSON()).includes('Threads run within a process.'));
    assert.deepEqual(view.starts,[]);
  } finally { if(view) act(()=>view.renderer.unmount()); restore(); }
});


test('normal conversation remembers replies, speaks them and never drafts an intent automatically', async () => {
  const restore=companionEnvironment(); let renderer;
  try {
    const requests=[], spoken=[], drafts=[];
    const voice={supported:true,active:false,target:null,phase:'idle',start(){},cancel(){},stop(){}};
    const speech={supported:false,active:false,speaking:false,speak:text=>spoken.push(text),stop(){}};
    const props={tasks:[],selected:null,page:'history',draft:'',online:true,busy:false,act(){},openIntent(){},requestVersion:0,voice,speech,
      onAsk:async (...args)=>{ requests.push(args); return {answer:requests.length===1?'Hi Mia!':'Your name is Mia.'}; },onDraftIntent:text=>drafts.push(text)};
    act(()=>{renderer=TestRenderer.create(React.createElement(RobotCompanion,props),{createNodeMock:()=>({style:{},focus(){}})});});
    act(()=>renderer.root.findByProps({className:'companion-hit'}).props.onClick());
    async function message(text) {
      act(()=>renderer.root.findByProps({id:'orbii-draft'}).props.onChange({target:{value:text}}));
      act(()=>renderer.root.findByType('form').props.onSubmit({preventDefault(){}}));
      await new Promise(resolve => setImmediate(resolve));
    }
    await message('My name is Mia.');
    await message('What is my name?');
    assert.deepEqual(requests[0],['My name is Mia.',[],null]);
    assert.deepEqual(requests[1],[ 'What is my name?', [{role:'user',content:'My name is Mia.'},{role:'assistant',content:'Hi Mia!'}], null]);
    assert.deepEqual(spoken,['Hi Mia!','Your name is Mia.']);
    assert.deepEqual(drafts,[]); assert.equal(completionPopup(renderer).length,0);
    assert.ok(JSON.stringify(renderer.toJSON()).includes('Your name is Mia.'));
    act(()=>renderer.root.findByProps({id:'orbii-draft'}).props.onChange({target:{value:'Create a report'}}));
    act(()=>renderer.root.findAllByType('button').find(b=>label(b)==='Use as intent ↗').props.onClick());
    assert.deepEqual(drafts,['Create a report']); assert.equal(requests.length,2);
  } finally { if(renderer) act(()=>renderer.unmount()); restore(); }
});

test('starting voice input stops speaker output before opening the microphone', () => {
  const restore=companionEnvironment(); let renderer, controller;
  try {
    const calls=[];
    window.SpeechRecognition=class {start(){calls.push('listen');} abort(){calls.push('abort');}};
    function Harness(){controller=useVoiceInput(()=>calls.push('stop speaking'));return null;}
    act(()=>{renderer=TestRenderer.create(React.createElement(Harness));});
    act(()=>controller.start({target:'orbii',value:'',onText(){}}));
    assert.deepEqual(calls,['stop speaking','listen']);
    act(()=>controller.cancel());
    assert.equal(calls.at(-1),'abort');
  } finally { if(renderer) act(()=>renderer.unmount()); restore(); }
});


test('text output is the initial default even with a legacy voice-enabled preference', () => {
  const restore=companionEnvironment(); let renderer, speech;
  try {
    localStorage.getItem=key=>key==='orbii-voice-enabled'?'true':null;
    const utterances=[];
    window.speechSynthesis={getVoices:()=>[{name:'Microsoft Zira',lang:'en-US',voiceURI:'zira'}],addEventListener(){},removeEventListener(){},cancel(){},speak:u=>utterances.push(u)};
    window.SpeechSynthesisUtterance=class {constructor(text){this.text=text;}};
    function Harness(){speech=useOrbiiSpeech();return React.createElement(OrbiiVoiceControls,{speech,recording:false});}
    act(()=>{renderer=TestRenderer.create(React.createElement(Harness));});
    assert.equal(speech.enabled,false);
    assert.equal(renderer.root.findByProps({value:'text'}).props.checked,true);
    act(()=>speech.speak('This stays as text.'));
    assert.equal(utterances.length,0);
    act(()=>renderer.root.findByProps({value:'voice'}).props.onChange());
    act(()=>speech.speak('Spoken because the user opted in.'));
    assert.equal(utterances.length,1);
    act(()=>renderer.root.findByProps({value:'text'}).props.onChange());
    act(()=>speech.speak('Back to text.'));
    assert.equal(utterances.length,1);
    act(()=>speech.speak('One explicit read-aloud.',{manual:true}));
    assert.equal(utterances.length,2); assert.equal(speech.enabled,false);
    act(()=>speech.stop());
    act(()=>renderer.unmount());
    act(()=>{renderer=TestRenderer.create(React.createElement(Harness));});
    assert.equal(speech.enabled,false);
  } finally { if(renderer) act(()=>renderer.unmount()); restore(); }
});
