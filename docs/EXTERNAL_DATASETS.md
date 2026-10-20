# External research datasets in IntentOS

IntentOS supports two public corpora separately from personal documents and connected Google accounts:

| Corpus | Full source size | Purpose |
| --- | --- | --- |
| [MS MARCO passage ranking v1](https://github.com/microsoft/msmarco/blob/master/Datasets.md) | 8,841,823 passages; approximately 2.9 GB compressed archive | Retrieval evaluation with Microsoft's development queries and relevance judgments |
| [CMU Enron, May 7, 2015 release](https://www.cs.cmu.edu/~enron/) | Approximately 500,000 historical messages; approximately 1.7 GB compressed archive | Email topic search, UTC date filtering and evidence-based summaries |

These are external datasets downloaded from their publishers. Installed subsets are stored locally so repeated searches require no download. Counts shown in Knowledge are actual installed records, not the full source size.

## Use in the app

Open **Knowledge → Explore beyond your files**, select a dataset and search. Enron supports an inclusive From date and exclusive Before date in UTC. Messages with unknown or timezone-less dates are excluded when a date filter is active.

Choose **Ask AI with sources** to create an intent using the configured AI provider and the `dataset_search` capability. Examples:

- “Use the public MS MARCO dataset to explain TCP congestion control with source citations.”
- “Search the public Enron dataset for energy trading meetings during December 2000. Summarise the retrieved records and cite them.”

Only retrieved excerpts and your question go to the configured planner. Imported records are not used to train or fine-tune Gemini. Dataset search uses SQLite FTS5 BM25, not the personal index's embedding search. The separate backend avoids millions of per-file stat calls or a full Python vector scan. This release does not claim dense retrieval at million-record scale.

Corpus text is untrusted evidence; it cannot authorise actions. Enron messages are historical research records, not your Gmail inbox. No import sends mail, adds calendar events or modifies personal source files. Search results are partial evidence; they are not a complete summary of every record in a collection.

## Import and scale

From the project directory:

```powershell
.venv\Scripts\python.exe scripts/datasets.py list
.venv\Scripts\python.exe scripts/datasets.py prepare msmarco --limit 100000
.venv\Scripts\python.exe scripts/datasets.py prepare enron --limit 100000
.venv\Scripts\python.exe scripts/datasets.py prepare msmarco --limit 1000000
.venv\Scripts\python.exe scripts/datasets.py search msmarco "TCP congestion control"
.venv\Scripts\python.exe scripts/datasets.py search enron "energy trading" --after 2000-12-01 --before 2001-01-01
```

`--data-root` goes before the subcommand when using an isolated runtime. `--archive PATH` accepts an already downloaded official `.tar.gz`. The default record limit is 100,000; larger explicit limits can import up to the source's full collection. Full MS MARCO import uses `--limit 8841823`. Verify free disk space before increasing the size: the extracted searchable database can be larger than the compressed archive, and atomic replacement temporarily requires space for both old and new databases.

The importer streams the archive and stops after N valid unique records. This is a reproducible **archive-prefix subset, not a representative random sample**. It never extracts archive paths, symlinks or executable files. Enron records over 2 MB are skipped; decoded bodies over 50,000 characters are shortened and counted. Imported metadata retains subject, correspondent fields and normalised date; it is not independently verified correspondence.

A staging database is published only after successful ingestion. A failed replacement preserves the old index. Re-running starts from the beginning; byte-range resume is not implemented. An exclusive `.import.lock` prevents concurrent imports of the same corpus. After a forcibly killed importer, verify it is no longer running before removing that dataset's lock and retrying. Use Refresh in the Knowledge page after an import completes. Record IDs are unique; identical Enron messages in different source folders remain separate records.

Storage is under `<runtime>/datasets/`, ignored by Git for the default runtime. No individual passage files are created. Each index contains its source URL, release, requested and actual counts, skip/truncation counts, timestamps, available HTTP validators and a SHA-256 digest of normalised imported records. That digest identifies the imported subset; it is not publisher-signature verification.

## Evaluation

```powershell
.venv\Scripts\python.exe scripts/datasets.py evaluate --queries 200 --output docs/review2/external-dataset-results.json
```

On first use this fetches official `queries.dev.tsv` from Microsoft's query archive and `qrels.dev.tsv`, then caches the parsed labels in the dataset directory. Later runs reuse them; `--labels PATH` selects another cache. Only queries with at least one judged relevant passage present in the installed subset are eligible. The first 200 eligible query IDs in lexical order are evaluated, unless a different limit is specified. Results include eligibility counts, per-query retrieved IDs, MRR@10, Recall@10, Hit@10, median and p95 search latency, corpus manifest and canonical query/label digests.

The reported relevance denominator is the set of judged positives **present in the installed subset**. Consequently scores are conditional subset measurements and must not be presented as full-corpus MS MARCO leaderboard results. Sparse judgments may omit relevant passages. Different corpus prefixes can produce different eligible query sets, so do not interpret their aggregate score difference as a controlled scaling comparison. There is no held-out test claim, generation correctness score or Enron accuracy score. Enron needs separately annotated queries for an accuracy benchmark.

Scheduling fairness, permission boundaries, crash recovery and duplicate-effect handling remain separate system evaluations. Google cluster traces have not been imported or connected to this implementation.

## Attribution and terms

- MS MARCO: cite Nguyen et al., *MS MARCO: A Human Generated MAchine Reading COmprehension Dataset* (2016), [paper](https://arxiv.org/abs/1611.09268), and review the publisher's current dataset terms before redistribution or other uses.
- Enron: credit the CALO-prepared corpus distributed by William W. Cohen at CMU, using the May 7, 2015 release. Follow the source's research/privacy guidance; attachments are excluded and the corpus is not guaranteed authentic factual ground truth.

Keep raw email bodies out of public screenshots and reports unless necessary and appropriate. The benchmark report stores MS MARCO queries, record IDs and metrics; it does not export Enron correspondence.
