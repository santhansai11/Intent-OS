"""Reproducible small-corpus retrieval experiment; never sends email.

Run with the six Computer Networks assessment DOCX files used for Review 2.
This is a developer-authored smoke benchmark, not a general accuracy claim.
"""
import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intent_kernel.config import Config
from services.capabilities import CapabilityRegistry

QUERIES = [
    ('hub broadcasts packets to every port', 'ASS1.docx'),
    ('minimum seven hosts hub and switch LAN simulation', 'ASS1.docx'),
    ('connect two LANs through one router', 'ASS 2.docx'),
    ('ISR4331 router and twenty end devices', 'ASS 2.docx'),
    ('star ring bus tree mesh hybrid topology', 'ASS3.docx'),
    ('hybrid network combining several topology types', 'ASS3.docx'),
    ('Stop-and-Wait ARQ lost acknowledgment retransmission', 'Ass 5.docx'),
    ('sender waits for confirmation before transmitting another frame', 'Ass 5.docx'),
    ('Python UDP socket chat server client', 'ASS 6.docx'),
    ('implement simple UDP sockets with socket module', 'ASS 6.docx'),
    ('classful IPv4 network broadcast address subnet mask', 'ass 7.docx'),
    ('calculate first and last address using bitwise operations', 'ass 7.docx'),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--model', default='nomic-embed-text')
    args = parser.parse_args()
    config = Config(args.data_root)
    config.values['embedding_model'] = args.model
    registry = CapabilityRegistry(config, None)
    index = registry.knowledge
    task = {'roots': [str(args.corpus.resolve())], 'search_roots': [str(args.corpus.resolve())]}
    paths = [args.corpus / name for name in dict.fromkeys(name for _, name in QUERIES)]
    started = time.perf_counter()
    cached = sum(index.index_file(p, task) for p in paths)
    initial = time.perf_counter() - started
    started = time.perf_counter()
    warm_cached = sum(index.index_file(p, task) for p in paths)
    refresh = time.perf_counter() - started
    result = {'date': time.strftime('%Y-%m-%d'), 'dataset': 'Six user-provided Computer Networks Lab DOCX assessments; PDF duplicates excluded',
              'documents': len(paths), 'source_bytes': sum(p.stat().st_size for p in paths),
              'model': args.model, 'python': platform.python_version(), 'platform': platform.platform(),
              'initial_index_seconds': round(initial, 3), 'initial_cache_hits': cached,
              'unchanged_refresh_seconds': round(refresh, 3), 'unchanged_cache_hits': warm_cached,
              'index': index.status(), 'modes': {},
              'limitations': '12 developer-authored queries, two per assessment, no held-out set, single laptop, no statistical significance or generation-quality measurement. Rank is first relevant unique document among returned passages. Timings are one run.'}
    for mode, model in [('BM25', ''), ('hybrid', args.model)]:
        config.values['embedding_model'] = model
        rows = []
        for query, expected in QUERIES:
            response = index.search({'query': query}, task)
            names = list(dict.fromkeys(m['name'] for m in response['matches']))
            rank = names.index(expected) + 1 if expected in names else None
            rows.append({'query': query, 'expected': expected, 'returned': names, 'rank': rank,
                         'latency_ms': response['latency_ms'], 'warning': response['warning']})
        result['modes'][mode] = {'hit_at_1': sum(r['rank'] == 1 for r in rows) / len(rows),
                                 'mrr_at_5': sum(1 / r['rank'] if r['rank'] and r['rank'] <= 5 else 0 for r in rows) / len(rows),
                                 'median_latency_ms': statistics.median(r['latency_ms'] for r in rows), 'queries': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({**{k: v for k, v in result.items() if k != 'modes'},
                      'modes': {k: {a: b for a, b in v.items() if a != 'queries'} for k, v in result['modes'].items()}}, indent=2))


if __name__ == '__main__':
    main()
