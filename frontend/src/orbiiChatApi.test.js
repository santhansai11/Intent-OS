import test from 'node:test';
import assert from 'node:assert/strict';
import { askOrbii } from './orbiiChatApi.js';

test('chat renews expired sessions after a restart and explains missing backend support', async () => {
  const original = globalThis.fetch, calls = [];
  const replies = [
    [200,{token:'old-session'}], [403,{error:'Refresh IntentOS to establish a local session'}],
    [200,{token:'new-session'}], [200,{answer:'Hello!'}], [404,{error:'Route not found'}],
    [400,{error:'Choose a model in Connections'}],
  ];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    const [status, body] = replies.shift();
    return {ok:status===200,status,json:async()=>body};
  };
  try {
    assert.deepEqual(await askOrbii('Hello',[],null),{answer:'Hello!'});
    assert.deepEqual(calls.map(c=>c[0]),['/api/session','/api/chat','/api/session','/api/chat']);
    assert.equal(calls[3][1].headers['X-IntentOS-Token'],'new-session');
    assert.equal(calls[1][1].body,calls[3][1].body);
    await assert.rejects(()=>askOrbii('Hello',[]),/Restart IntentOS/);
    await assert.rejects(()=>askOrbii('Hello',[]),/Choose a model/);
    assert.equal(calls.length,6);
  } finally { globalThis.fetch = original; }
});
