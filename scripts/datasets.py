"""Install, search and evaluate public datasets without touching personal files."""
import argparse
import hashlib
import json
import statistics
import sys
import tarfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intent_kernel.config import Config
from services.datasets import BASE, CATALOG, DatasetStore, remote


def evaluate(store, queries, qrels, query_limit=200):
    """Evaluate only queries with a judged positive in the installed corpus.

    The explicit conditioning makes subset scores unsuitable for comparison with
    the full MS MARCO leaderboard. Unjudged results are counted as nonrelevant.
    """
    if query_limit < 1:
        raise ValueError('Query limit must be positive')
    eligible = []
    with store.read('msmarco') as db:
        manifest = json.loads(db.execute('SELECT data FROM manifest').fetchone()[0])
        for qid in sorted(queries):
            relevant = qrels.get(qid, set())
            present = {pid for pid in relevant if db.execute('SELECT 1 FROM documents WHERE id=?', (pid,)).fetchone()}
            if present:
                eligible.append((qid, present))
    rows = []
    for qid, relevant in eligible[:query_limit]:
        result = store.search({'dataset': 'msmarco', 'query': queries[qid]}, limit=10)
        ids = [m['record_id'] for m in result['matches']]
        ranks = [i for i, pid in enumerate(ids, 1) if pid in relevant]
        rows.append({'query_id': qid, 'query': queries[qid], 'relevant_in_subset': sorted(relevant),
                     'returned_ids': ids, 'reciprocal_rank_at_10': 1 / ranks[0] if ranks else 0,
                     'recall_at_10': len(ranks) / len(relevant), 'latency_ms': result['latency_ms']})
    if not rows:
        raise ValueError('No judged positives overlap the installed subset. Import more records.')
    times = sorted(r['latency_ms'] for r in rows)
    return {'dataset': 'MS MARCO passage ranking v1', 'engine': 'SQLite FTS5 BM25',
            'queries_sha256': hashlib.sha256(json.dumps(queries, sort_keys=True).encode()).hexdigest(),
            'qrels_sha256': hashlib.sha256(json.dumps({q: sorted(p) for q, p in qrels.items()}, sort_keys=True).encode()).hexdigest(),
            'manifest': manifest, 'queries_available': len(queries), 'queries_with_positive_in_subset': len(eligible),
            'queries_without_positive_in_subset': len(queries) - len(eligible), 'queries_evaluated': len(rows),
            'query_selection': 'First eligible query IDs in lexical order from official development queries',
            'mrr_at_10': statistics.mean(r['reciprocal_rank_at_10'] for r in rows),
            'recall_at_10': statistics.mean(r['recall_at_10'] for r in rows),
            'hit_at_10': statistics.mean(int(r['reciprocal_rank_at_10'] > 0) for r in rows),
            'median_latency_ms': statistics.median(times), 'p95_latency_ms': times[max(0, (95 * len(times) + 99) // 100 - 1)],
            'limitations': 'Archive-prefix corpus; conditional subset evaluation, not a full-corpus leaderboard score. '
                            'Development queries only, no held-out test claim. Sparse judgments; no generation accuracy, '
                            'hybrid retrieval, scheduler, permissions or recovery measurement. Single run, warm/cold cache not controlled.',
            'results': rows}


def official_labels(cache=None):
    if cache and cache.is_file():
        data = json.loads(cache.read_text(encoding='utf-8'))
        return data['queries'], {qid: set(pids) for qid, pids in data['qrels'].items()}
    qrels = {}
    with remote(BASE + 'qrels.dev.tsv') as response:
        for line in response:
            qid, _, pid, relevance = line.decode('utf-8').split()
            if int(relevance) > 0:
                qrels.setdefault(qid, set()).add(pid)
    queries = {}
    with remote(BASE + 'queries.tar.gz') as response, tarfile.open(fileobj=response, mode='r|gz') as archive:
        for member in archive:
            if member.isfile() and PurePosixPath(member.name).name == 'queries.dev.tsv':
                with archive.extractfile(member) as raw:
                    for line in raw:
                        qid, text = line.decode('utf-8').rstrip('\r\n').split('\t', 1)
                        queries[qid] = text
                break
    if not queries:
        raise ValueError('Official query archive is missing queries.dev.tsv')
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        # Publish complete labels only. The corpus importer never reads this file.
        pending = cache.with_suffix('.partial')
        pending.write_text(json.dumps({'queries': queries, 'qrels': {q: sorted(p) for q, p in qrels.items()}}), encoding='utf-8')
        pending.replace(cache)
    return queries, qrels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, help='Defaults to the app runtime directory')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list')
    prepare = commands.add_parser('prepare')
    prepare.add_argument('dataset', choices=CATALOG)
    prepare.add_argument('--limit', type=int, default=100000)
    prepare.add_argument('--archive', type=Path, help='Use an existing official tar.gz instead of HTTPS')
    search = commands.add_parser('search')
    search.add_argument('dataset', choices=CATALOG)
    search.add_argument('query')
    search.add_argument('--after', help='Enron date inclusive YYYY-MM-DD, UTC')
    search.add_argument('--before', help='Enron date exclusive YYYY-MM-DD, UTC')
    evaluation = commands.add_parser('evaluate')
    evaluation.add_argument('--queries', type=int, default=200)
    evaluation.add_argument('--labels', type=Path, help='JSON query/qrels cache; fetched from Microsoft if absent')
    evaluation.add_argument('--output', type=Path, default=Path('output/evaluation/external-dataset-results.json'))
    args = parser.parse_args()
    store = DatasetStore(Config(args.data_root).root)
    if args.command == 'list':
        result = store.catalog()
    elif args.command == 'prepare':
        result = store.prepare(args.dataset, args.limit, args.archive,
                               lambda n: print(f'Indexed {n:,} records', file=sys.stderr, flush=True))
    elif args.command == 'search':
        result = store.search(vars(args))
    else:
        queries, qrels = official_labels(args.labels or store.root / 'msmarco-dev-labels.json')
        result = evaluate(store, queries, qrels, args.queries)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        result = {k: v for k, v in result.items() if k != 'results'}
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
