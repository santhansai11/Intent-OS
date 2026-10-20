import React, { useEffect, useState } from 'react';
import { api } from './api';

export default function Datasets({ perform, busy, open }) {
  const [catalog, setCatalog] = useState([]);
  const [error, setError] = useState('');
  const [dataset, setDataset] = useState('msmarco');
  const [query, setQuery] = useState('');
  const [after, setAfter] = useState('');
  const [before, setBefore] = useState('');
  const [result, setResult] = useState(null);
  const refresh = () => api('/datasets').then(r => { setCatalog(r.datasets); setError(''); }).catch(e => setError(e.message));
  useEffect(() => { refresh(); }, []);
  const selected = catalog.find(d => d.id === dataset);
  return <section className="external-datasets">
    <div className="section-title"><div><div className="eyebrow">PUBLIC RESEARCH COLLECTIONS</div><h2>Explore beyond your files</h2></div><button onClick={refresh}>Refresh</button></div>
    <p className="retrieval-label">Search external benchmark data, separate from your documents and connected inbox.</p>
    {error && <p className="notice" role="alert">{error}</p>}
    <div className="dataset-grid">{catalog.map(d => <button key={d.id} disabled={busy} className={`dataset-card ${dataset === d.id ? 'selected' : ''}`} aria-pressed={dataset === d.id} onClick={() => { setDataset(d.id); setResult(null); }}>
      <span className="eyebrow">{d.id === 'msmarco' ? 'PASSAGE RETRIEVAL' : 'HISTORICAL EMAIL'}</span>
      <h3>{d.name}</h3><strong>{d.installed ? d.installed.records.toLocaleString() : 'Not installed'}</strong>
      <span>{d.installed ? 'indexed records' : 'Ready to import'}</span>
      <small>Full source: {d.total_records.toLocaleString()}{d.id === 'enron' ? ' (approx.)' : ''}</small>
    </button>)}</div>
    {selected && <>
      <form className="dataset-form" onSubmit={e => { e.preventDefault(); perform(async () => setResult(await api('/datasets/search', { dataset, query, ...(dataset === 'enron' ? { after, before } : {}) }))); }}>
        <label className="dataset-query">Search {selected.name}<input value={query} onChange={e => setQuery(e.target.value)} placeholder={dataset === 'msmarco' ? 'How does TCP congestion control work?' : 'Meetings about energy trading'} required maxLength={2000}/></label>
        {dataset === 'enron' && <div className="field-row"><label>From (UTC, inclusive)<input type="date" value={after} onInput={e => setAfter(e.target.value)}/></label><label>Before (UTC, exclusive)<input type="date" value={before} onInput={e => setBefore(e.target.value)}/></label></div>}
        <div className="button-row"><button className="primary" disabled={busy || !selected.installed || !query.trim()}>Search dataset →</button><button type="button" disabled={busy || !selected.installed || !query.trim()} onClick={() => perform(async () => {
          const text = `Use dataset_search on the public ${dataset} dataset to answer: ${query}. ${dataset === 'enron' ? `Date constraints in UTC: after ${after || 'none'} inclusive, before ${before || 'none'} exclusive.` : ''} Cite the retrieved evidence. Identify it as public benchmark data and do not claim it comes from my files or Gmail.`;
          open(await api('/intents', { text, scopes: ['system', 'web'] }));
        })}>Ask AI with sources</button></div>
      </form>
      <details className="settings-card"><summary>Dataset source & import details</summary><p><a href={selected.source} target="_blank" rel="noreferrer">Official dataset source ↗</a> · {selected.release}</p><p>{selected.terms}</p><p>Archive-order samples, not random samples. Search uses BM25 without embeddings. Importing again replaces this dataset's index after successful completion.</p><code className="dataset-command">.venv\Scripts\python.exe scripts/datasets.py prepare {dataset} --limit 100000</code>{selected.installed && <p>Imported {new Date(selected.installed.imported_utc).toLocaleString()} · {selected.installed.truncated_records} shortened records · {selected.installed.skipped_records} skipped records</p>}</details>
    </>}
    {result && <><div className="section-title"><h3>{result.matches.length} public records</h3><span>{result.latency_ms} ms · BM25</span></div>{result.matches.map(r => <article className="retrieval-card" key={r.source_id}><div><span className="citation">{r.citation}</span><b>{r.name}</b></div><p>{r.excerpt}</p><details><summary>Record provenance</summary><p>{r.record_id}</p>{r.metadata.date && <p>{r.metadata.date}</p>}<p>{r.coverage}{r.metadata.truncated ? ' Imported body was shortened.' : ''}</p></details></article>)}{!result.matches.length && <div className="empty">No matching records in this installed sample. Try another topic or date range.</div>}</>}
  </section>;
}
