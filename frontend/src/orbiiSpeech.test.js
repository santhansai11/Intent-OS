import test from 'node:test';
import assert from 'node:assert/strict';
import { chooseOrbiiVoice, createOrbiiSpeech, spokenChunks } from './orbiiSpeech.js';
import { chatHistory } from './chatHistory.js';

test('voice selection prefers a feminine English voice and honors explicit selection', () => {
  const voices=[{name:'Default',lang:'en-US',default:true,voiceURI:'default'},{name:'Microsoft Zira',lang:'en-US',voiceURI:'zira'}];
  assert.equal(chooseOrbiiVoice(voices).name,'Microsoft Zira');
  assert.equal(chooseOrbiiVoice(voices,'default').name,'Default');
  assert.equal(chooseOrbiiVoice([]),undefined);
});

test('spoken text removes markdown and breaks long replies into complete bounded chunks', () => {
  const chunks=spokenChunks('## Hello **friend**. [Read more](https://example.com). '+ 'A useful sentence. '.repeat(60));
  assert.ok(chunks.length>2); assert.ok(chunks.every(c=>c.length<=220));
  assert.ok(chunks.join(' ').startsWith('Hello friend. Read more.'));
  assert.equal((chunks.join(' ').match(/A useful sentence\./g)||[]).length,60);
});

function setup() {
  const spoken=[], phases=[], errors=[];
  const synthesis={cancel(){},speak:u=>spoken.push(u)};
  class Utterance { constructor(text) {this.text=text;} }
  const engine=createOrbiiSpeech({synthesis,Utterance,onPhase:p=>phases.push(p),onError:e=>errors.push(e)});
  return {engine,spoken,phases,errors};
}

test('playback reports speaking only after audio starts and cancellation prevents queued chunks', () => {
  const s=setup();
  s.engine.speak('Hello friend. '.repeat(40),{name:'Zira',lang:'en-US'});
  assert.equal(s.phases.at(-1),'preparing');
  const first=s.spoken[0], lateEnd=first.onend;
  assert.equal(first.voice.name,'Zira'); assert.equal(first.pitch,1.16);
  first.onstart(); assert.equal(s.phases.at(-1),'speaking');
  s.engine.stop(); lateEnd();
  assert.equal(s.spoken.length,1); assert.equal(s.phases.at(-1),'idle');
});

test('a playback error leaves readable text available and reports a retry option', () => {
  const s=setup(); s.engine.speak('Hello');
  s.spoken[0].onerror({error:'not-allowed'});
  assert.equal(s.phases.at(-1),'idle'); assert.match(s.errors[0],/Read aloud/);
});

test('chat context keeps recent whole messages within the backend budget', () => {
  const history=chatHistory(Array.from({length:30},(_,i)=>({role:i%2?'assistant':'user',content:String(i).padEnd(2000,'x')})));
  assert.equal(history.length,8); assert.ok(history.at(-1).content.startsWith('29'));
  assert.equal(history.reduce((n,m)=>n+m.content.length,0),16000);
});
