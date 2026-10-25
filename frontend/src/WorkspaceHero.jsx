import React from 'react';
import { Icon } from './ui';

export default function WorkspaceHero() {
  return <section className="studio-hero" aria-labelledby="workspace-heading">
    <div className="hero-honeycomb" aria-hidden="true">{Array.from({length: 9}, (_, i) => <i key={i}/>)}</div>
    <div className="hero-copy">
      <div className="hero-eyebrow"><span/> MEET YOUR PERSONAL AI WORKSPACE</div>
      <h1 id="workspace-heading"><span>Big ideas.</span><span className="gradient-text">A little curiosity.</span><span>Consider it done.</span></h1>
      <p>Give your goal a place to run.<br/>Think, create, and get things moving<br className="desktop-break"/> with a little help from IntentOS.</p>
      <button className="hero-link" onClick={() => document.getElementById('goal')?.focus()}>Let’s make it happen <span>↗</span></button>
      <div className="hero-footnote"><Icon name="shield" size={14}/> Your workspace. Your permissions.</div>
    </div>
    <div className="hero-character" id="orbii-home">
      <span className="hero-particle particle-one" aria-hidden="true"/><span className="hero-particle particle-two" aria-hidden="true"/><span className="hero-particle particle-three" aria-hidden="true"/>
      <div className="character-caption"><span className="status-dot"/> Meet Orbii. Click to say hello.</div>
    </div>
    <div className="hero-note"><span className="hero-note-icon"><Icon name="spark" size={20}/></span><div><b>From intent to action.</b><small>You bring the idea. We’ll bring the tools.</small></div></div>
  </section>;
}
