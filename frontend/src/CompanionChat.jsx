import React from 'react';
import Answer from './Answer';
import VoiceInput from './VoiceInput';

export default function CompanionChat({ task, value, onText, onSubmit, voice, busy, online, messages = [], speech, onDraftIntent, onDiscuss, onClear, contextActive }) {
  const recording = voice.active && voice.target === 'orbii';
  return <div className="orbii-chat">
    {task?.goal && <p className="orbii-chat-context">You asked: {task.goal.split('\n')[0]}</p>}
    {task && !task.answer && <p className="orbii-chat-progress" role="status">{({READY:'Your message is queued.',RUNNING:'Working on your message…',RECOVERY:'Waiting to retry your message.',APPROVAL:'This message needs permission.',WAITING_INPUT:'This message needs more information.',REVIEW:'This message needs review.',FAILED:'This message could not be completed.',BLOCKED:'This message needs attention.',PAUSED:'This message is paused.',CANCELLED:'This message was cancelled.'})[task.state] || 'Open the intent to check its progress.'}</p>}
    {task?.answer && <div className="orbii-answer" aria-label="Orbii’s answer"><Answer text={task.answer}/>
      {speech?.supported && <button type="button" disabled={voice.active} onClick={() => speech.speak(task.answer, {manual:true})}>Read result aloud</button>}
      {onDiscuss && !contextActive && <button type="button" disabled={busy} onClick={() => onDiscuss(task.id)}>Discuss this result</button>}
    </div>}
    {(messages.length > 0 || contextActive) && <div className="orbii-chat-toolbar"><span>{contextActive?'Chat about this result':'Just chatting'}</span><button type="button" disabled={busy} onClick={onClear}>New chat</button></div>}
    <div className="orbii-messages" role="log" aria-label="Conversation with Orbii" aria-live="polite">{messages.map((message,index) => <article className={'orbii-message '+message.role} key={index}>
      <small>{message.role === 'user'?'You':'Orbii'}</small><Answer text={message.content}/>
      {message.role === 'assistant' && speech?.supported && <button type="button" disabled={voice.active} onClick={() => speech.speak(message.content, {manual:true})}>Read aloud</button>}
      {message.role === 'user' && onDraftIntent && <button type="button" disabled={busy || voice.active} onClick={() => onDraftIntent(message.content)}>Make this an intent ↗</button>}
    </article>)}</div>
    {busy && <p role="status" className="orbii-chat-progress">Orbii is thinking…</p>}
    <form onSubmit={event => { event.preventDefault(); if (value.trim() && value.length <= 4000 && !busy && online && !voice.active) onSubmit(value.trim()); }}>
      <label htmlFor="orbii-draft">Ask Orbii</label>
      <textarea id="orbii-draft" rows={3} maxLength={4000} value={value} readOnly={recording || busy} onChange={event => onText(event.target.value)} placeholder="Say hello, ask a question, or talk it through…"/>
      <VoiceInput voice={voice} target="orbii" value={value} onText={onText} disabled={busy || !online}/>
      <button className="primary" disabled={busy || !online || voice.active || !value.trim() || value.length > 4000}>{busy?'Thinking…':'Send message ↗'}</button>
      {onDraftIntent && <button type="button" disabled={busy || voice.active || !value.trim()} onClick={() => onDraftIntent(value.trim())}>Use as intent ↗</button>}
      {value.length > 4000 && <p role="alert">Keep chat messages under 4,000 characters, or use the intent workspace.</p>}
      <small className="orbii-chat-note">Normal talk doesn’t create intents or run tools. Conversation stays in this tab until you refresh. Use as intent opens a draft for you to review.</small>
    </form>
  </div>;
}
