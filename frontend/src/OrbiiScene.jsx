import React, { useEffect, useRef, useState } from 'react';

export default function OrbiiScene({ interaction, paused, tone = 'idle' }) {
  const host = useRef(null), controller = useRef(null);
  const pausedRef = useRef(paused);
  const [ready, setReady] = useState(false);
  useEffect(() => { pausedRef.current = paused; controller.current?.(); }, [paused]);
  useEffect(() => { interaction.current.tone = tone; controller.current?.(); }, [tone, interaction]);
  useEffect(() => {
    let disposed = false, cleanup = () => {};
    const element = host.current;
    // Defer the WebGL bundle until the scene is near the viewport.
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      import('./orbiiRenderer.js').then(({ createOrbii }) => {
        if (disposed) return;
        const scene = createOrbii(element, interaction, pausedRef, () => setReady(false));
        cleanup = scene.dispose;
        controller.current = scene.refresh;
        setReady(true);
      }).catch(() => { if (!disposed) setReady(false); });
    }, { rootMargin: '120px' });
    observer.observe(element);
    return () => { disposed = true; observer.disconnect(); cleanup(); controller.current = null; };
  }, [interaction]);
  return <div className={'orbii-scene mood-'+tone+' '+(ready?'is-ready':'')} role="img" aria-label={`Orbii, your AI companion. ${tone} mood.`}>
    <div className="orbii-fallback" aria-hidden="true"><div className="fallback-body"><div className="fallback-rim"><div className="fallback-face"><i/><i/><span className="fallback-cheek left"/><span className="fallback-cheek right"/></div></div></div><div className="fallback-shadow"/></div>
    <div className="orbii-listening-rings" aria-hidden="true"><i/><i/></div>
    <div className="orbii-canvas" ref={host} aria-hidden="true"/>
  </div>;
}
