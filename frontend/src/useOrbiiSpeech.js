import { useEffect, useRef, useState } from 'react';
import { chooseOrbiiVoice, createOrbiiSpeech } from './orbiiSpeech';

export default function useOrbiiSpeech() {
  const engine = useRef(null);
  const [voices, setVoices] = useState([]), [phase, setPhase] = useState('idle'), [error, setError] = useState('');
  // Each visit starts with text replies, including upgrades from older builds
  // that automatically persisted voice-enabled=true.
  const [enabled, setEnabled] = useState(false);
  const [preferred, setPreferred] = useState(() => localStorage.getItem('orbii-voice-name') || '');
  const supported = typeof window !== 'undefined' && !!window.speechSynthesis && !!window.SpeechSynthesisUtterance;
  const selected = chooseOrbiiVoice(voices, preferred);
  function stop() { engine.current?.stop(); }
  function speak(text, { manual = false } = {}) {
    if ((!enabled && !manual) || !supported || document.hidden || !text?.trim()) return;
    setError(''); engine.current?.speak(text, selected);
  }
  useEffect(() => {
    if (!supported) return;
    const synthesis = window.speechSynthesis;
    engine.current = createOrbiiSpeech({synthesis,Utterance:window.SpeechSynthesisUtterance,onPhase:setPhase,onError:setError});
    const refresh = () => setVoices(synthesis.getVoices());
    const hide = () => { if (document.hidden) stop(); };
    refresh(); synthesis.addEventListener('voiceschanged', refresh); document.addEventListener('visibilitychange', hide);
    return () => { synthesis.removeEventListener('voiceschanged', refresh); document.removeEventListener('visibilitychange', hide); stop(); engine.current = null; };
  }, [supported]);
  useEffect(() => { if (!enabled) stop(); }, [enabled]);
  useEffect(() => { localStorage.setItem('orbii-voice-name', preferred); stop(); }, [preferred]);
  return { supported, enabled, setEnabled, voices, preferred, setPreferred, voiceName: selected?.name || 'Browser default', phase, speaking: phase === 'speaking', active: phase !== 'idle', error, speak, stop };
}
