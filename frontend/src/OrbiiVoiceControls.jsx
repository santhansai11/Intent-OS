import React from 'react';

export default function OrbiiVoiceControls({ speech, recording }) {
  if (!speech.supported) return <small className="orbii-chat-note">Spoken replies aren’t available in this browser. Replies still appear here.</small>;
  return <div className="orbii-output-controls">
    <fieldset className="orbii-output-format"><legend>Reply format</legend>
      <label><input type="radio" name="orbii-reply-format" value="text" checked={!speech.enabled} onChange={() => speech.setEnabled(false)}/>Text</label>
      <label><input type="radio" name="orbii-reply-format" value="voice" checked={speech.enabled} onChange={() => speech.setEnabled(true)}/>Text + voice</label>
    </fieldset>
    <details className="orbii-voice-settings"><summary>Voice options</summary>
    <div className="orbii-voice-actions">
      <button type="button" aria-pressed={speech.enabled} onClick={() => speech.setEnabled(!speech.enabled)}>{speech.enabled?'Mute replies':'Speak replies'}</button>
      <button type="button" disabled={!speech.active} onClick={speech.stop}>Stop speaking</button>
    </div>
    <label>Voice<select value={speech.preferred} onChange={event => speech.setPreferred(event.target.value)}>
      <option value="">Automatic · gentle female preference</option>
      {speech.voices.map(v=><option key={v.voiceURI || v.name} value={v.voiceURI || v.name}>{v.name} · {v.lang}</option>)}
    </select></label>
    <small>Using {speech.voiceName}. Availability and sound depend on your device. Some voices use an online service.</small>
    <button type="button" disabled={recording} onClick={() => speech.speak('Hi, I’m Orbii! I’m here whenever you want to talk.', {manual:true})}>Preview voice</button>
  </details></div>;
}
