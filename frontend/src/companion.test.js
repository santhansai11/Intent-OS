import test from 'node:test';
import assert from 'node:assert/strict';
import { companionState, companionPlacement, companionSide, chooseCompanionTask, conversationKey, draftKind, permissionQuestion, PALETTES } from './companionModel.js';

test('runtime states take priority over a draft when permission or input is required', () => {
  for (const [state, tone] of [['APPROVAL','approval'],['REVIEW','review'],['WAITING_INPUT','input']]) {
    assert.equal(companionState({task:{state},draft:'Write a report',composing:true}).tone,tone);
  }
  assert.equal(companionState({task:{state:'RUNNING'},online:false}).tone,'offline');
  assert.equal(companionState({task:{state:'COMPLETED'}}).tone,'completed');
  assert.equal(companionState({task:{state:'FAILED'}}).tone,'error');
  assert.equal(companionState({task:{state:'PAUSED'}}).tone,'paused');
});

test('draft colors respond locally to intent categories without executing an action', () => {
  for (const [draft, kind] of [['Schedule a meeting','meeting'],['Research TCP','research'],['Gather files','files'],['Write a report','writing'],['','idle']]) {
    assert.equal(draftKind(draft),kind);
    assert.equal(companionState({draft}).tone,kind);
    assert.equal(PALETTES[kind].length,2);
  }
});

test('the request under review stays pinned when another task enters the queue', () => {
  const tasks = [{id:'new',state:'APPROVAL'},{id:'reviewing',state:'APPROVAL'},{id:'selected',state:'RUNNING'}];
  assert.equal(chooseCompanionTask(tasks,'selected','reviewing').id,'reviewing');
  tasks[1].state='RUNNING';
  assert.equal(chooseCompanionTask(tasks,'selected','reviewing').id,'new');
  assert.notEqual(conversationKey({id:'a',state:'APPROVAL',pending:{id:'one'}}),conversationKey({id:'a',state:'APPROVAL',pending:{id:'two'}}));
});

test('the robot shrinks on scroll and returns to its hero', () => {
  const base={width:1440,height:900,pointer:{x:900,y:450},composing:false,composerTop:600,panelOpen:false,reduced:false,parked:false};
  const home={left:850,top:230,width:450,height:440};
  const start=companionPlacement({...base,home});
  const mid=companionPlacement({...base,home:{...home,top:20}});
  const dock=companionPlacement({...base,home:{...home,top:-200}});
  assert.equal(start.size,410); assert.equal(start.docked,false);
  assert.ok(mid.size<start.size && mid.size>dock.size);
  assert.equal(dock.size,112); assert.ok(dock.x>base.pointer.x); assert.equal(dock.docked,true);
  assert.deepEqual(companionPlacement({...base,home}),start);
});

test('cursor travel stays bounded at desktop, tablet and mobile sizes', () => {
  for (const width of [375,768,1024,1440]) {
    for (const point of [{x:-1000,y:-1000},{x:5000,y:5000}]) {
      const result=companionPlacement({width,height:800,home:null,pointer:point,composerTop:160});
      assert.ok(result.x>=0 && result.x+result.size<=width);
      assert.ok(result.y>=0 && result.y+result.size<=800);
    }
  }
});

test('typing docks beside the composer; paused and reduced motion stop pointer travel', () => {
  const base={width:1440,height:900,home:{left:850,top:230,width:450,height:440},pointer:{x:900,y:450},composerTop:250};
  const composer={left:180,right:900,top:250,bottom:500};
  const watching=companionPlacement({...base,composing:true,composer});
  assert.ok(watching.x>composer.right || watching.y+watching.size<composer.top);
  for (const mode of [{reduced:true},{parked:true}]) {
    assert.deepEqual(companionPlacement({...base,...mode,pointer:{x:0,y:0}}),companionPlacement({...base,...mode,pointer:{x:1440,y:900}}));
  }
});

test('unknown capabilities do not invent a harmless description', () => {
  assert.match(permissionQuestion({tool:'unknown_operation'}),/unknown operation/);
  assert.match(permissionQuestion({tool:'gmail_send'}),/send this email/);
  assert.match(permissionQuestion({tool:'calendar_delete'}),/delete/);
});


test('compact placement switches screen edges and follows cursor height', () => {
  const base={width:1440,height:900,home:null};
  const left=companionPlacement({...base,pointer:{x:250,y:200}});
  const right=companionPlacement({...base,pointer:{x:1000,y:550}});
  assert.equal(left.x,12);
  assert.equal(right.x+right.size,1440-12);
  assert.ok(right.y>left.y);
  assert.equal(left.x,companionPlacement({...base,pointer:{x:300,y:700}}).x);
  assert.ok(companionPlacement({...base,pointer:{x:300,y:700}}).y>left.y);
  assert.equal(companionPlacement({...base,pointer:{x:1200,y:400},panelOpen:true,side:'left'}).x,12);
});

test('side selection has a center dead zone and locks while interacting', () => {
  assert.equal(companionSide(1440,200,'right'),'left');
  assert.equal(companionSide(1440,1200,'left'),'right');
  assert.equal(companionSide(1440,730,'left'),'left');
  assert.equal(companionSide(1440,710,'right'),'right');
  assert.equal(companionSide(1440,200,'right',true),'right');
  assert.equal(companionSide(375,20,'right'),'right');
});
