import React, { useEffect, useRef, useState } from 'react';
import OrbiiScene from './OrbiiScene';
import ActionConversation from './ActionConversation';
import CompanionChat from './CompanionChat';
import OrbiiVoiceControls from './OrbiiVoiceControls';
import { chatHistory } from './chatHistory';
import { chooseCompanionTask, companionPlacement, companionSide, companionState, conversationKey, NEEDS_ATTENTION, PALETTES } from './companionModel';
const SILENT = { supported:false, active:false, speaking:false, stop(){}, speak(){} };

export default function RobotCompanion({ tasks, selected, page, draft, online, busy, act, openIntent, requestVersion, voice, onAsk, speech = SILENT, onDraftIntent }) {
  const interaction = useRef({ x: 0, y: 0, excited: false, tone: 'idle' });
  const visual = useRef(null), status = useRef(null), trigger = useRef(null), closeButton = useRef(null);
  const pointer = useRef({ x: 600, y: 350 }), position = useRef(null);
  const sideRef = useRef('right');
  const [side, setSide] = useState('right');
  const observedStates = useRef(new Map()), celebrated = useRef(new Set()), mountedAt = useRef(Date.now() / 1000);
  const [finishedIds, setFinishedIds] = useState([]);
  const [lastFinishedId, setLastFinishedId] = useState(null);
  const finishedTasks = finishedIds.map(id => tasks.find(t => t.id === id && t.state === 'COMPLETED')).filter(Boolean);
  const completion = finishedTasks[0];
  const [open, setOpen] = useState(false), [docked, setDocked] = useState(false), [composing, setComposing] = useState(false);
  const [pinnedId, setPinnedId] = useState(null), [chatId, setChatId] = useState(null);
  const [chatDraft, setChatDraft] = useState('');
  const [messages, setMessages] = useState([]), [chatPending, setChatPending] = useState(false), [chatError, setChatError] = useState('');
  const [chatContextId, setChatContextId] = useState(null);
  const chatGeneration = useRef(0), chatInFlight = useRef(false);
  const latest = useRef({open, voice, speech}); latest.current = {open, voice, speech};
  useEffect(() => () => { chatGeneration.current++; }, []);
  const [paused, setPaused] = useState(() => localStorage.getItem('intent-orbii-paused') === 'true');
  const [parked, setParked] = useState(() => localStorage.getItem('intent-orbii-parked') === 'true');
  const watchingComposer = composing || (voice.active && voice.target === 'goal');
  const task = chooseCompanionTask(tasks, chatId || (page === 'workspace' ? selected : null) || lastFinishedId, pinnedId);
  const chatTask = tasks.find(t => t.id === chatId);
  const attention = task && NEEDS_ATTENTION.includes(task.state);
  const conversationTask = !open && (composing || draft.trim()) && !attention ? null : task;
  const baseState = open && online && !attention && (chatDraft.trim() || messages.length || !task)
    ? { tone:'attentive', label:'Let’s talk', message:'I’m here. We can talk, ask questions, or explore an idea together.' }
    : companionState({ task, draft: open ? '' : draft, online, page, composing });
  const state = voice.active ? { tone: voice.phase === 'listening' ? 'listening' : 'attentive', label: voice.phase === 'listening' ? 'Listening to you' : voice.phase === 'stopping' ? 'Finishing voice input' : 'Microphone requested', message: 'Your words will appear in the draft. Review them, then send when you’re ready.' }
    : speech.speaking ? { tone:'speaking', label:'Speaking to you', message:'You can stop or mute my voice at any time.' }
    : chatPending ? { tone:'working', label:'Thinking…', message:'Let me think about that.' }
    : completion && !attention ? { tone: 'completed', label: 'Intent finished!', message: 'All done! Your answer is ready to read.' }
    : open && baseState.tone === 'idle' ? { ...baseState, tone: 'attentive', label: 'You have my attention' } : baseState;
  const key = conversationKey(task);
  const announced = useRef(new Set());
  const actionInFlight = useRef(false);
  const [sending, setSending] = useState(false), [actionError, setActionError] = useState('');

  useEffect(() => {
    const newlyFinished = [];
    for (const item of tasks) {
      const before = observedStates.current.get(item.id);
      // Loading old history is not a new completion. Also catch fast intents
      // created during this visit that finish between snapshots.
      if (item.state === 'COMPLETED' && !celebrated.current.has(item.id) &&
          ((before && before !== 'COMPLETED') || (!before && item.created_at >= mountedAt.current))) {
        celebrated.current.add(item.id); newlyFinished.push(item.id);
      }
      observedStates.current.set(item.id, item.state);
    }
    if (newlyFinished.length) { setFinishedIds(old => [...old, ...newlyFinished]); setLastFinishedId(newlyFinished.at(-1)); if (!latest.current.voice.active && !latest.current.speech.active) latest.current.speech.speak('Your intent is finished! Your answer is ready.'); }
  }, [tasks]);

  useEffect(() => {
    if (attention && !announced.current.has(key)) {
      announced.current.add(key); speech.stop(); voice.cancel(); setPinnedId(task.id); setOpen(true);
    }
  }, [attention, key, task?.id]);
  useEffect(() => { if (requestVersion) { setChatId(null); setPinnedId(selected); setOpen(true); } }, [requestVersion]);
  useEffect(() => { setActionError(''); }, [key]);
  useEffect(() => {
    localStorage.setItem('intent-orbii-paused', String(paused));
    document.documentElement.dataset.orbiiPaused = String(paused);
    return () => { delete document.documentElement.dataset.orbiiPaused; };
  }, [paused]);
  useEffect(() => { localStorage.setItem('intent-orbii-parked', String(parked)); }, [parked]);
  useEffect(() => {
    function focus(event) { setComposing(event.target.id === 'goal'); }
    function blur(event) { if (event.target.id === 'goal') setComposing(false); }
    document.addEventListener('focusin', focus); document.addEventListener('focusout', blur);
    return () => { document.removeEventListener('focusin', focus); document.removeEventListener('focusout', blur); };
  }, []);
  useEffect(() => {
    if (!open) return;
    function keydown(event) { if (event.key === 'Escape') { closeConversation(); trigger.current?.focus({ preventScroll: true }); } }
    document.addEventListener('keydown', keydown);
    return () => document.removeEventListener('keydown', keydown);
  }, [open, voice.target]);

  // One canvas survives route changes. Only its compositor transform changes.
  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0, previous = 0, lastDocked = null, active = true;
    let home = null, composerTop = 150, width = window.innerWidth, height = window.innerHeight;
    function measure() {
      width = window.innerWidth; height = window.innerHeight;
      const anchor = document.getElementById('orbii-home');
      home = anchor ? anchor.getBoundingClientRect() : null;
      composerTop = document.getElementById('goal')?.getBoundingClientRect().top ?? 150;
      wake();
    }
    function move(event) {
      if (event.pointerType === 'touch') return;
      const current = position.current;
      // Let the pointer reach Orbii instead of making the button run away.
      if (event.target.closest?.('.robot-companion') || (current && Math.hypot(event.clientX - current.x - current.size / 2, event.clientY - current.y - current.size / 2) < current.size * .8)) return;
      pointer.current = { x: event.clientX, y: event.clientY };
      interaction.current.excited = !!event.target.closest?.('.hero-link, .run-button, .new-intent');
      wake();
    }
    function draw(now) {
      frame = 0;
      if (!active || document.hidden) return;
      const edge = companionSide(width, pointer.current.x, sideRef.current, open || !!completion || parked || paused || reduced.matches);
      if (sideRef.current !== edge) { sideRef.current = edge; setSide(edge); }
      const target = companionPlacement({ width, height, home, pointer: pointer.current, composing: watchingComposer, panelOpen: open || !!completion, reduced: reduced.matches, parked: parked || paused, side: edge });
      const dt = previous ? Math.min((now - previous) / 1000, .05) : .016; previous = now;
      const blend = reduced.matches || paused ? 1 : 1 - Math.exp(-7 * dt);
      const current = position.current || target;
      ['x', 'y', 'size'].forEach(k => { current[k] += (target[k] - current[k]) * blend; });
      position.current = current;
      visual.current.style.transform = `translate3d(${current.x}px,${current.y}px,0) scale(${current.size / 400})`;
      visual.current.style.visibility = 'visible';
      status.current.style.transform = `translate3d(${current.x}px,${current.y + current.size - 6}px,0)`;
      status.current.style.width = `${current.size}px`;
      if (lastDocked !== target.docked) { lastDocked = target.docked; setDocked(target.docked); }
      const lookingAt = watchingComposer ? { x: width * .55, y: composerTop + 55 } : pointer.current;
      interaction.current.x = Math.max(-1, Math.min(1, (lookingAt.x - current.x - current.size / 2) / Math.max(200, width * .4)));
      interaction.current.y = Math.max(-1, Math.min(1, (lookingAt.y - current.y - current.size / 2) / Math.max(200, height * .4)));
      const unsettled = ['x', 'y', 'size'].some(k => Math.abs(current[k] - target[k]) > .1);
      if (unsettled && !reduced.matches && !paused) frame = requestAnimationFrame(draw);
    }
    function wake() { if (!frame && active && !document.hidden) { previous = 0; frame = requestAnimationFrame(draw); } }
    const observer = new ResizeObserver(measure);
    observer.observe(document.querySelector('main'));
    window.addEventListener('pointermove', move, { passive: true });
    window.addEventListener('scroll', measure, { passive: true }); window.addEventListener('resize', measure);
    document.addEventListener('visibilitychange', wake); reduced.addEventListener('change', measure);
    measure();
    return () => {
      active = false; cancelAnimationFrame(frame); observer.disconnect();
      window.removeEventListener('pointermove', move); window.removeEventListener('scroll', measure); window.removeEventListener('resize', measure);
      document.removeEventListener('visibilitychange', wake); reduced.removeEventListener('change', measure);
    };
  }, [page, selected, watchingComposer, open, parked, paused, completion?.id]);

  async function send(id, action, data) {
    if (actionInFlight.current || busy || !online) return;
    actionInFlight.current = true; setSending(true); setActionError('');
    try { await act(id, action, data); }
    catch (error) { setActionError(error.message); }
    finally { actionInFlight.current = false; setSending(false); }
  }
  async function ask(text) {
    if (chatInFlight.current || !online || voice.active || text.length > 4000) return;
    chatInFlight.current = true; setChatPending(true); setChatError(''); speech.stop();
    const generation = ++chatGeneration.current;
    const nextMessages = [...messages, {role:'user',content:text}];
    setMessages(nextMessages); setChatDraft('');
    try {
      const result = await onAsk(text, chatHistory(messages), chatContextId);
      if (generation !== chatGeneration.current) return;
      setMessages([...nextMessages, {role:'assistant',content:result.answer}].slice(-40));
      if (latest.current.open && !latest.current.voice.active) latest.current.speech.speak(result.answer);
    } catch (error) { if (generation === chatGeneration.current) { setChatError(error.message); setMessages(messages); setChatDraft(text); } }
    finally { if (generation === chatGeneration.current) { chatInFlight.current = false; setChatPending(false); } }
  }
  function resetChat(contextId = null) {
    chatGeneration.current++; chatInFlight.current = false; setChatPending(false); setChatError('');
    setMessages([]); setChatContextId(contextId); speech.stop();
  }
  function closeConversation() { speech.stop(); if (voice.target === 'orbii') voice.cancel(); setOpen(false); }
  function dismissCompletion() { setFinishedIds(old => old.filter(id => id !== completion.id)); }
  function showAnswer() {
    voice.cancel(); resetChat(completion.id); setChatId(completion.id); setOpen(true); dismissCompletion();
    requestAnimationFrame(() => closeButton.current?.focus({ preventScroll: true }));
  }
  function toggle() {
    if (open) { closeConversation(); return; }
    voice.cancel(); speech.stop();
    setOpen(true);
    requestAnimationFrame(() => document.getElementById('orbii-draft')?.focus({ preventScroll: true }));
  }
  const colors = PALETTES[state.tone];
  const waiting = tasks.filter(t => NEEDS_ATTENTION.includes(t.state));
  const completionNotice = completion && <aside className="orbii-completion" aria-label="Intent finished notification">
    <div role="status"><span className="completion-check" aria-hidden="true">✓</span><strong>Intent finished</strong>{finishedTasks.length > 1 && <small>{finishedTasks.length} finished</small>}</div>
    <p>{completion.goal.split('\n')[0]}</p>
    <div className="completion-actions"><button className="primary" onClick={showAnswer}>Read answer ↗</button><button aria-label="Dismiss intent finished notification" onClick={dismissCompletion}>Dismiss</button></div>
  </aside>;
  return <div className={'robot-companion side-'+side+' '+(docked?'is-docked ':'')+(open?'conversation-open ':'')+('stage-'+state.tone)} style={{ '--orbii-start': colors[0], '--orbii-end': colors[1] }}>
    <div className="companion-visual" ref={visual}>
      <OrbiiScene interaction={interaction} paused={paused} tone={state.tone}/>
      <button className="companion-hit" ref={trigger} onClick={toggle} aria-label={open?'Close Orbii conversation':`Chat with Orbii: ${state.label}`} aria-expanded={open} aria-controls="orbii-conversation"/>
    </div>
    <div className="companion-status" ref={status}><button onClick={toggle} aria-expanded={open} aria-controls="orbii-conversation"><span/>{state.label}{attention && <b aria-label="Needs attention">!</b>}</button></div>
    <span className="sr-only" role="status" aria-live="polite">{state.label}{attention ? '. Orbii has a request for you.' : ''}</span>
    {!open && completionNotice}
    {open && <section id="orbii-conversation" className="companion-panel" role="region" aria-labelledby="orbii-title">
      <header><span className="orbii-mini" aria-hidden="true"><i/><i/></span><div><h2 id="orbii-title">Orbii</h2><small>{state.label}</small></div><button ref={closeButton} aria-label="Minimize Orbii conversation" onClick={() => { closeConversation(); trigger.current?.focus({ preventScroll: true }); }}>×</button></header>
      <div className="companion-conversation">
        {completionNotice}
        {waiting.length > 1 && <label className="orbii-queue">{waiting.length} intents need attention<select value={task?.id || ''} disabled={busy || sending} onChange={event => setPinnedId(event.target.value)}>{waiting.map(t => <option key={t.id} value={t.id}>{t.goal.split('\n')[0]}</option>)}</select></label>}
        {conversationTask && <div className="orbii-intent-context"><span>ABOUT THIS INTENT</span><p>{conversationTask.goal.split('\n')[0]}</p><button className="text-button" onClick={() => openIntent(conversationTask)}>View intent ↗</button></div>}
        {!['APPROVAL', 'REVIEW', 'WAITING_INPUT'].includes(conversationTask?.state) && <p className="orbii-speech">{state.message}</p>}
        {conversationTask && <ActionConversation key={key} task={conversationTask} busy={busy || sending} online={online} act={send}/>}
        {!online && <p className="orbii-caution">The runtime is offline. I’ll enable these choices when it reconnects.</p>}
        {actionError && <p className="orbii-caution" role="alert">{actionError}</p>}
        {sending && <p role="status">Sending your choice…</p>}
        {chatError && <p className="orbii-caution" role="alert">{chatError}</p>}
        <OrbiiVoiceControls speech={speech} recording={voice.active}/>
        <CompanionChat messages={messages} speech={speech} onDiscuss={resetChat} onClear={() => resetChat()} contextActive={!!chatContextId} onDraftIntent={onDraftIntent ? text => { closeConversation(); onDraftIntent(text); } : undefined} task={tasks.find(t => t.id === chatContextId) || (attention ? chatTask : conversationTask)} value={chatDraft} onText={setChatDraft} onSubmit={ask} voice={voice} busy={chatPending} online={online}/>
        {speech.error && <p className="voice-error" role="alert">{speech.error}</p>}
        {speech.active && <button type="button" className="text-button" onClick={speech.stop}>Stop speaking</button>}
        {conversationTask?.state === 'COMPLETED' && <button className="text-button" onClick={() => { closeConversation(); openIntent(conversationTask); }}>View sources & intent details ↗</button>}
      </div>
      <footer className="companion-preferences"><button aria-pressed={parked} onClick={() => setParked(!parked)}>{parked?'Switch sides with cursor':'Stay on this side'}</button><button aria-pressed={paused} onClick={() => setPaused(!paused)}>{paused?'Play motion':'Pause motion'}</button></footer>
    </section>}
  </div>;
}
