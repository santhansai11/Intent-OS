import React from 'react';
export const SCOPE_NAMES = { files: 'Local files', web: 'Web', calendar: 'Calendar', drive: 'Drive', maps: 'Maps', gmail: 'Gmail', meet: 'Meet' };
export function Icon({ name, size = 19 }) {
  const paths = {
    mic: <><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></>,
    stop: <rect x="6" y="6" width="12" height="12" rx="2"/>,
    menu: <path d="M4 6h16M4 12h16M4 18h16"/>,
    close: <path d="m6 6 12 12M6 18 18 6"/>,
    spark: <><path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3Z"/><path d="m20 2 .7 2.3L23 5l-2.3.7L20 8l-.7-2.3L17 5l2.3-.7Z"/></>,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
    activity: <path d="M2 12h5l3-8 4 16 3-8h5"/>,
    plug: <><path d="M8 3v5m8-5v5M7 8h10v4a5 5 0 0 1-10 0ZM12 17v5"/></>,
    arrow: <path d="M12 20V4m-6 6 6-6 6 6"/>,
    file: <><path d="M14 3H5v18h14V8Zm0 0v5h5M8 12h8m-8 4h6"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    chevron: <path d="m9 5 7 7-7 7"/>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.spark}</svg>;
}

export function Badge({ state }) { return <span className={'badge state-' + state}>{state.replaceAll('_', ' ').toLowerCase()}</span>; }

