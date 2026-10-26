import React, { useState } from 'react';
import { fieldLabel, permissionQuestion } from './companionModel';

function ActionValue({ value }) {
  if (Array.isArray(value)) return value.length ? <ul>{value.map((item, index) => <li key={index}><ActionValue value={item}/></li>)}</ul> : <span>None</span>;
  if (value && typeof value === 'object') return <dl>{Object.entries(value).map(([key, item]) => <div key={key}><dt>{fieldLabel(key)}</dt><dd><ActionValue value={item}/></dd></div>)}</dl>;
  return <span>{value == null ? 'Not specified' : typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)}</span>;
}

// Remounted for each exact request, so replies and risk acknowledgements never
// carry over to a different intent or action.
export default function ActionConversation({ task, busy, online, act }) {
  const [reply, setReply] = useState(''), [risk, setRisk] = useState(false);
  const pending = task.pending;
  const disabled = busy || !online;
  if (task.state === 'WAITING_INPUT') return <form className="orbii-question" onSubmit={event => { event.preventDefault(); if (!disabled && reply.trim()) act(task.id, 'reply', { text: reply }); }}>
    <p>{task.question || 'What else should I know before continuing?'}</p>
    <label htmlFor="orbii-reply">Tell Orbii<textarea id="orbii-reply" value={reply} onChange={event => setReply(event.target.value)} maxLength={12000} rows={3} placeholder="Write your answer…"/></label>
    <button className="primary" disabled={disabled || !reply.trim()}>Send reply <span aria-hidden="true">↗</span></button>
  </form>;
  if (!pending || !['APPROVAL', 'REVIEW'].includes(task.state)) return null;
  return <div className="orbii-permission">
    <h3>{task.state === 'REVIEW' ? 'Let’s check what happened first.' : permissionQuestion(pending)}</h3>
    {pending.summary && <p>{pending.summary}</p>}
    {task.state === 'REVIEW' && <p className="orbii-caution">This action may already have happened. Check the destination before retrying so we don’t repeat it.</p>}
    {['gmail_send', 'gmail_draft'].includes(pending.tool) && <p className="orbii-action-scope">One email to all listed recipients. {pending.mail_files?.length ? `${pending.mail_files.length} file(s) attached.` : 'No files attached.'}</p>}
    {pending.mail_files?.length > 0 && <ul aria-label="Email attachment details">{pending.mail_files.map(file => <li key={file.path}>{file.name} · {(file.bytes / 1024).toFixed(1)} KB</li>)}</ul>}
    <dl className="orbii-action-fields">{Object.entries(pending.arguments || {}).map(([key, value]) => <div key={key}><dt>{fieldLabel(key)}</dt><dd><ActionValue value={value}/></dd></div>)}</dl>
    {task.state === 'APPROVAL' ? <><p className="orbii-action-scope">Your choice applies only to this action.</p><div className="orbii-actions"><button className="primary" disabled={disabled} onClick={() => act(task.id, 'approve', { action_id: pending.id })}>Allow this action</button><button disabled={disabled} onClick={() => act(task.id, 'deny', { action_id: pending.id })}>Don’t allow</button></div></>
      : <><label className="folder-check"><input type="checkbox" checked={risk} onChange={event => setRisk(event.target.checked)}/>I checked the destination and understand a retry could duplicate this action.</label><div className="orbii-actions"><button className="primary" disabled={disabled || !risk} onClick={() => act(task.id, 'retry', { action_id: pending.id, acknowledge_duplicate_risk: true })}>Retry this action</button><button disabled={disabled} onClick={() => act(task.id, 'skip', {})}>Skip this action</button></div></>}
  </div>;
}
