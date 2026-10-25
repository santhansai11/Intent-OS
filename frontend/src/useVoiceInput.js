import { useEffect, useRef, useState } from 'react';
import { createSpeechSession } from './speechInput';

export default function useVoiceInput(beforeStart) {
  const session = useRef(null);
  const [phase, setPhase] = useState('idle'), [target, setTarget] = useState(null);
  const [interim, setInterim] = useState(''), [error, setError] = useState('');
  const supported = typeof window !== 'undefined' && !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  function cancel() { session.current?.cancel(); session.current = null; }
  function start({ target: nextTarget, value, onText }) {
    beforeStart?.();
    cancel(); setError(''); setInterim(''); setTarget(nextTarget);
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) { setError('Voice input is not supported in this browser. You can type your intent below.'); return; }
    const next = createSpeechSession({ Recognition, value, onText, onPhase: setPhase, onInterim: setInterim, onError: setError,
      onEnd: () => { if (session.current === next) session.current = null; } });
    session.current = next; next.start();
  }
  useEffect(() => {
    const hide = () => { if (document.hidden) cancel(); };
    document.addEventListener('visibilitychange', hide);
    return () => { document.removeEventListener('visibilitychange', hide); cancel(); };
  }, []);
  return { supported, phase, target, interim, error, start, stop: () => session.current?.stop(), cancel, active: phase !== 'idle' };
}
