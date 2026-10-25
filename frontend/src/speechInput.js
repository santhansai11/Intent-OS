export const speechErrorMessage = code => ({
  'not-allowed': 'Microphone access was denied. Enable it in your browser’s site permissions, or type your intent.',
  'service-not-allowed': 'Speech recognition is unavailable in this browser session. You can still type your intent.',
  'audio-capture': 'No microphone is available. Connect a microphone, or type your intent.',
  'no-speech': 'I didn’t catch any speech. Try again when you’re ready.',
  network: 'The browser’s speech service could not connect. Try again, or type your intent.',
  'language-not-supported': 'This speech language is unavailable. You can type your intent instead.',
}[code] || 'Voice input stopped. Your confirmed words are kept; you can edit them or try again.');

// One deliberate recording session. Recognition never dispatches an intent.
export function createSpeechSession({ Recognition, value = '', language = 'en-IN', onText, onInterim, onPhase, onError, onEnd }) {
  const recognition = new Recognition();
  recognition.lang = language;
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;
  let active = true, started = false, timer, lastFinal = '';
  const initial = value.trimEnd();
  function cleanup() {
    clearTimeout(timer);
    recognition.onstart = recognition.onresult = recognition.onerror = recognition.onend = null;
  }
  function finish() {
    if (!active) return;
    active = false; cleanup(); onInterim(''); onPhase('idle'); onEnd?.();
  }
  recognition.onstart = () => {
    if (!active) return;
    started = true;
    onPhase('listening');
    timer = setTimeout(stop, 60000);
  };
  recognition.onresult = event => {
    if (!active) return;
    const final = [], interim = [];
    for (let i = 0; i < event.results.length; i++) {
      const result = event.results[i];
      (result.isFinal ? final : interim).push(result[0].transcript);
    }
    const confirmed = final.join(' ').trim();
    if (confirmed && confirmed !== lastFinal) {
      lastFinal = confirmed;
      onText([initial, confirmed].filter(Boolean).join(' ').slice(0, 12000));
    }
    onInterim(interim.join(' ').trim());
  };
  recognition.onerror = event => { if (active && event.error !== 'aborted') onError(speechErrorMessage(event.error)); finish(); };
  recognition.onend = finish;
  function cancel() { if (!active) return; finish(); try { recognition.abort(); } catch { /* Already stopped. */ } }
  function stop() {
    if (!active) return;
    if (!started) { cancel(); return; }
    clearTimeout(timer); onPhase('stopping');
    try { recognition.stop(); if (active) timer = setTimeout(cancel, 3000); } catch { cancel(); }
  }
  return {
    start() { onPhase('requesting'); try { recognition.start(); } catch (error) { onError(speechErrorMessage(error.name === 'NotAllowedError' ? 'not-allowed' : 'service-not-allowed')); finish(); } },
    stop,
    cancel,
  };
}
