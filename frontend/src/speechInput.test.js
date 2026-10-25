import test from 'node:test';
import assert from 'node:assert/strict';
import { createSpeechSession } from './speechInput.js';
import { faceExpression } from './expressions.js';

function setup(value = '') {
  let engine;
  class Recognition {
    constructor() { engine = this; this.stopped = 0; this.aborted = 0; }
    start() {}
    stop() { this.stopped++; }
    abort() { this.aborted++; }
  }
  const text=[], interim=[], phases=[], errors=[];
  const session = createSpeechSession({Recognition,value,onText:v=>text.push(v),onInterim:v=>interim.push(v),onPhase:v=>phases.push(v),onError:v=>errors.push(v)});
  return {session,engine,text,interim,phases,errors};
}
const result = (text, final) => Object.assign([{transcript:text}], {isFinal:final});

test('interim speech stays separate; confirmed words append to the draft exactly once', () => {
  const s=setup('Explain'); s.session.start();
  assert.deepEqual(s.phases,['requesting']);
  s.engine.onstart();
  s.engine.onresult({results:[result('photosynthesis',false)]});
  assert.deepEqual(s.text,[]); assert.equal(s.interim.at(-1),'photosynthesis');
  s.engine.onresult({results:[result('photosynthesis',true)]});
  s.engine.onresult({results:[result('photosynthesis',true),result('simply',false)]});
  assert.deepEqual(s.text,['Explain photosynthesis']);
  s.engine.onresult({results:[result('photosynthesis',true),result('simply',true)]});
  assert.equal(s.text.at(-1),'Explain photosynthesis simply');
  s.session.stop(); assert.equal(s.engine.stopped,1);
  s.engine.onend(); assert.equal(s.phases.at(-1),'idle');
});

test('cancellation releases the microphone and ignores late results', () => {
  const s=setup(); s.session.start(); s.engine.onstart();
  const late=s.engine.onresult; s.session.cancel();
  late({results:[result('allow this action',true)]});
  assert.deepEqual(s.text,[]); assert.equal(s.engine.aborted,1);
  assert.equal(s.engine.onresult,null); assert.equal(s.phases.at(-1),'idle');
});

test('stopping while permission is pending cancels without pretending to listen', () => {
  const s=setup(); s.session.start(); const late=s.engine.onstart;
  s.session.stop(); late();
  assert.deepEqual(s.phases,['requesting','idle']); assert.equal(s.engine.aborted,1);
});

test('permission and network failures keep confirmed text with a useful fallback', () => {
  for (const error of ['not-allowed','audio-capture','network','no-speech']) {
    const s=setup(); s.session.start(); s.engine.onstart();
    s.engine.onresult({results:[result('My question',true)]});
    s.engine.onerror({error});
    assert.equal(s.text.at(-1),'My question'); assert.ok(s.errors[0].length>20);
    assert.equal(s.phases.at(-1),'idle'); assert.equal(s.engine.onresult,null);
  }
});

test('listening, celebration and uncertainty have distinct facial expressions', () => {
  assert.ok(faceExpression('listening').height > faceExpression('idle').height);
  assert.equal(faceExpression('completed').eyes,'happy');
  assert.equal(faceExpression('review').brows,true);
  assert.equal(faceExpression('idle').eyes,'round');
});
