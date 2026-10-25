import { useEffect } from 'react';

// Progressive enhancement: content remains visible if observers or motion fail.
export default function useWorkspaceMotion(page, selected) {
  useEffect(() => {
    const root = document.getElementById('main-content');
    if (!root) return;
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const animations = new Set();
    let current = null, frame = 0, pointer = null;
    function clearTilt() {
      current?.style.removeProperty('--card-x');
      current?.style.removeProperty('--card-y');
      current = null;
    }
    const observer = new IntersectionObserver(entries => {
      entries.filter(entry => entry.isIntersecting).forEach((entry, index) => {
        observer.unobserve(entry.target);
        if (preference.matches || !entry.target.animate) return;
        const animation = entry.target.animate([
          { opacity: .25, translate: '0 15px' },
          { opacity: 1, translate: '0 0' },
        ], { duration: 550, delay: Math.min(index * 45, 180), easing: 'cubic-bezier(.22,1,.36,1)' });
        animations.add(animation);
        animation.onfinish = () => animations.delete(animation);
      });
    }, { threshold: .08 });
    root.querySelectorAll('.workflow-grid>button, .workspace-context, .activity-list, .settings-card, .metric-grid>div, .lab-card, .external-datasets').forEach(element => observer.observe(element));
    function move(event) {
      if (preference.matches || event.pointerType === 'touch') return;
      const card = event.target.closest('.workflow-grid>button, .dataset-card');
      if (card !== current) { clearTilt(); current = card; }
      if (!current) return;
      pointer = { x: event.clientX, y: event.clientY };
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!current) return;
        const rect = current.getBoundingClientRect();
        current.style.setProperty('--card-x', `${-(pointer.y - rect.top - rect.height / 2) / rect.height * 5}deg`);
        current.style.setProperty('--card-y', `${(pointer.x - rect.left - rect.width / 2) / rect.width * 5}deg`);
      });
    }
    function leave(event) { if (!current?.contains(event.relatedTarget)) clearTilt(); }
    function stop() { if (preference.matches) { animations.forEach(animation => animation.cancel()); animations.clear(); clearTilt(); } }
    root.addEventListener('pointermove', move);
    root.addEventListener('pointerout', leave);
    preference.addEventListener('change', stop);
    return () => {
      observer.disconnect(); cancelAnimationFrame(frame); clearTilt(); animations.forEach(animation => animation.cancel());
      root.removeEventListener('pointermove', move); root.removeEventListener('pointerout', leave); preference.removeEventListener('change', stop);
    };
  }, [page, selected]);
}
