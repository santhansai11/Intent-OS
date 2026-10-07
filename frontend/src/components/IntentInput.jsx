import React, { useState } from "react";

const EXAMPLES = [
  "Prepare everything for my 4 PM meeting.",
  "Show my schedule for today",
  "Submit my assignment to the professor",
  "Download the lecture videos",
  "Remind me to call mom at 18:30",
];

export default function IntentInput({ onSubmit, busy }) {
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);

  const submit = (e) => {
    e.preventDefault();
    const value = text.trim();
    if (!value || busy) return;
    onSubmit(value);
    setText("");
  };

  const startVoice = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      alert("Voice input requires the Web Speech API (Chrome/Edge).");
      return;
    }
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.onstart = () => setListening(true);
    rec.onend = () => setListening(false);
    rec.onresult = (event) => {
      const said = event.results[0][0].transcript;
      setText(said);
      onSubmit(said);
    };
    rec.start();
  };

  return (
    <section className="panel">
      <h2>What do you want to accomplish?</h2>
      <form onSubmit={submit}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={'e.g. "Prepare everything for my 4 PM meeting."'}
          rows={3}
          disabled={busy}
        />
        <div className="row">
          <button type="submit" className="primary" disabled={busy || !text.trim()}>
            RUN
          </button>
          <button type="button" className="voice" onClick={startVoice} disabled={busy}>
            {listening ? "Listening..." : "🎤 Voice"}
          </button>
        </div>
      </form>
      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} className="chip" onClick={() => onSubmit(ex)} disabled={busy}>
            {ex}
          </button>
        ))}
      </div>
    </section>
  );
}
