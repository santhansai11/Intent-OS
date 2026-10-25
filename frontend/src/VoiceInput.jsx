import React from 'react';
import { Icon } from './ui';

export default function VoiceInput({ voice, target, value, onText, disabled = false }) {
  const own = voice.target === target, recording = own && voice.active;
  return <div className={'voice-input '+(recording?'is-recording':'')}>
    <button type="button" className="voice-button" disabled={disabled && !recording} aria-label={recording?'Stop voice input':'Use voice input'} aria-pressed={recording} onClick={() => recording ? voice.stop() : voice.start({ target, value, onText })}>
      <Icon name={recording?'stop':'mic'} size={17}/>{recording?'Stop listening':'Use voice'}
    </button>
    {recording && <span className="voice-phase" role="status"><span className="voice-bars" aria-hidden="true"><i/><i/><i/><i/></span>{voice.phase === 'requesting' ? 'Waiting for microphone…' : voice.phase === 'stopping' ? 'Finishing…' : 'Listening…'}</span>}
    {own && voice.interim && <p className="voice-interim" role="status">{voice.interim}</p>}
    {own && voice.error && <p className="voice-error" role="alert">{voice.error}</p>}
    <small>{voice.supported ? 'Browser speech recognition may use an online service. Review your words before sending.' : 'Voice isn’t available in this browser. Typing is always available.'}</small>
  </div>;
}
