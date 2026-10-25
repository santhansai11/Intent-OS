// Browsers expose names and languages, but no standardized gender field.
// Prefer familiar feminine voice names; the user can select any installed voice.
export function chooseOrbiiVoice(voices, preferred = '') {
  return voices.find(v => (v.voiceURI || v.name) === preferred)
    || voices.find(v => /^en/i.test(v.lang) && /zira|aria|jenny|sonia|samantha|heera|neerja|karen|moira|tessa|susan|victoria|female/i.test(v.name))
    || voices.find(v => /^en/i.test(v.lang) && v.default)
    || voices.find(v => /^en/i.test(v.lang)) || voices.find(v => v.default) || voices[0];
}

export function spokenChunks(text) {
  const plain = text.replace(/```[\s\S]*?```/g, ' Code is shown in the conversation. ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/https?:\/\/\S+/g, 'link in the conversation')
    .replace(/[#*_`>|]/g, '').replace(/\s+/g, ' ').trim();
  const chunks = [];
  let rest = plain;
  while (rest.length) {
    let end = Math.min(220, rest.length);
    if (end < rest.length) { const space = rest.lastIndexOf(' ', end); if (space > 0) end = space; }
    chunks.push(rest.slice(0, end)); rest = rest.slice(end).trimStart();
  }
  return chunks;
}

export function createOrbiiSpeech({ synthesis, Utterance, onPhase, onError }) {
  let generation = 0, current = null, timer;
  function stop() {
    generation++; clearTimeout(timer);
    if (current) current.onstart = current.onend = current.onerror = null;
    current = null; synthesis.cancel(); onPhase('idle');
  }
  function speak(text, voice) {
    stop(); const id = generation, chunks = spokenChunks(text);
    function next() {
      if (id !== generation) return;
      if (!chunks.length) { clearTimeout(timer); current = null; onPhase('idle'); return; }
      const utterance = new Utterance(chunks.shift()); current = utterance;
      if (voice) { utterance.voice = voice; utterance.lang = voice.lang; }
      else utterance.lang = 'en-IN';
      utterance.pitch = 1.16; utterance.rate = .97; utterance.volume = 1;
      const fail = () => { if (id !== generation) return; stop(); onError('Voice playback could not start or finish. Try Read aloud, or choose another voice.'); };
      utterance.onstart = () => { if (id !== generation) return; clearTimeout(timer); onPhase('speaking'); timer = setTimeout(fail, 45000); };
      utterance.onend = () => { if (id !== generation) return; clearTimeout(timer); next(); };
      utterance.onerror = event => { if (id !== generation) return; if (['canceled','interrupted'].includes(event.error)) stop(); else fail(); };
      onPhase('preparing'); timer = setTimeout(fail, 10000);
      try { synthesis.speak(utterance); } catch { fail(); }
    }
    next();
  }
  return { speak, stop };
}
