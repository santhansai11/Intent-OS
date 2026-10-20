"""Public corpus ingestion, provenance, isolation and benchmark correctness."""
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from intent_kernel.config import Config
from services.contracts import validate_completion
from services.datasets import DatasetStore
from services.summary_policy import PlanCorrection
from scripts.datasets import evaluate, official_labels
from planner.document_context import document_context


class Datasets(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = DatasetStore(self.root)

    def archive(self, entries, name='fixture.tar.gz'):
        path = self.root / name
        with tarfile.open(path, 'w:gz') as out:
            for filename, content in entries:
                member = tarfile.TarInfo(filename)
                if content is None:
                    member.type = tarfile.SYMTYPE
                    member.linkname = '../outside'
                    out.addfile(member)
                else:
                    raw = content.encode()
                    member.size = len(raw)
                    out.addfile(member, io.BytesIO(raw))
        return path

    def corpus(self):
        archive = self.archive([('collection.tsv', '1\tTCP congestion window\n2\tEnergy trading meeting\n3\tNetwork packet routing\n')])
        return self.store.prepare('msmarco', 3, archive)

    def test_prefix_is_bounded_reproducible_and_not_mixed(self):
        archive = self.archive([('collection.tsv', '1\tTCP congestion window\n1\tDuplicate\n2\tRouting packets\n3\tIgnore me\n')])
        first = self.store.prepare('msmarco', 2, archive)
        second = self.store.prepare('msmarco', 2, archive)
        self.assertEqual(first['subset_sha256'], second['subset_sha256'])
        self.assertEqual(second['records'], 2)
        self.assertEqual(second['skipped_records'], 1)
        self.assertEqual(self.store.search({'dataset': 'msmarco', 'query': 'Ignore'})['matches'], [])
        self.assertIsNone(self.store.catalog()[1]['installed'])

    def test_no_archive_paths_or_links_are_extracted(self):
        archive = self.archive([('../outside', 'bad'), ('/absolute', 'bad'),
                                ('maildir/link', None), ('collection.tsv', '1\tSafe corpus text\n')])
        result = self.store.prepare('msmarco', 1, archive)
        self.assertEqual(result['skipped_members'], 3)
        self.assertFalse((self.root / 'outside').exists())
        self.assertFalse((self.root / 'collection.tsv').exists())

    def test_failed_replacement_preserves_previous_index(self):
        original = self.corpus()
        broken = self.root / 'broken.tar.gz'
        broken.write_bytes(b'not an archive')
        with self.assertRaises(tarfile.ReadError):
            self.store.prepare('msmarco', 5, broken)
        self.assertEqual(self.store.catalog()[0]['installed']['subset_sha256'], original['subset_sha256'])
        self.assertEqual(len(self.store.search({'dataset': 'msmarco', 'query': 'TCP'})['matches']), 1)
        self.assertFalse(list(self.store.root.glob('*.import.lock')))
        self.assertFalse(list(self.store.root.glob('*.staging.sqlite3')))

    def test_concurrent_import_does_not_remove_another_lock(self):
        self.corpus()
        lock = self.store.root / 'msmarco.import.lock'
        lock.touch()
        with self.assertRaises(FileExistsError):
            self.store.prepare('msmarco', 5)
        self.assertTrue(lock.exists())

    def test_empty_invalid_and_oversized_records_do_not_publish(self):
        for text in ('invalid line\n', '1\t' + 'x' * 1_000_001):
            archive = self.archive([('collection.tsv', text)])
            with self.assertRaises(ValueError):
                self.store.prepare('msmarco', 2, archive)
        self.assertFalse(self.store.path('msmarco').exists())

    def test_query_syntax_is_data_and_ids_cannot_escape(self):
        self.corpus()
        for ident in ('../msmarco', 'gmail', None, []):
            with self.assertRaises(ValueError):
                self.store.search({'dataset': ident, 'query': 'TCP'})
        for query in ('', None, 'x' * 2001):
            with self.assertRaises(ValueError):
                self.store.search({'dataset': 'msmarco', 'query': query})
        self.assertTrue(self.store.search({'dataset': 'msmarco', 'query': '"TCP" OR (NEAR *'})['matches'])

    def test_enron_decoding_and_utc_exclusive_dates(self):
        def mail(date, body):
            return f'Subject: Trading meeting\nDate: {date}\nFrom: a@example.com\nContent-Type: text/plain; charset=utf-8\n\n{body}'
        archive = self.archive([('maildir/a/1', mail('Fri, 01 Dec 2000 20:00:00 -0800', 'Energy trading')),
                                ('maildir/a/2', mail('Sun, 03 Dec 2000 00:00:00 +0000', 'Energy trading')),
                                ('maildir/a/3', mail('unknown', 'Energy trading'))])
        self.store.prepare('enron', 3, archive)
        found = self.store.search({'dataset': 'enron', 'query': 'energy', 'after': '2000-12-02', 'before': '2000-12-03'})
        self.assertEqual([r['record_id'] for r in found['matches']], ['maildir/a/1'])
        self.assertEqual(found['matches'][0]['metadata']['date'], '2000-12-02T04:00:00+00:00')
        for after, before in [('2000-12-03', '2000-12-02'), ('garbage', ''), (True, ''), ('2000-1-2', '')]:
            with self.assertRaises(ValueError):
                self.store.search({'dataset': 'enron', 'query': 'energy', 'after': after, 'before': before})

    def test_metrics_condition_on_present_positives(self):
        self.corpus()
        report = evaluate(self.store, {'q1': 'TCP', 'q2': 'energy', 'q3': 'missing'},
                          {'q1': {'1'}, 'q2': {'2'}, 'q3': {'999'}}, 10)
        self.assertEqual(report['queries_evaluated'], 2)
        self.assertEqual(report['queries_without_positive_in_subset'], 1)
        self.assertEqual(report['mrr_at_10'], 1)
        self.assertEqual(report['recall_at_10'], 1)
        self.assertIn('not a full-corpus', report['limitations'])

    def test_cached_queries_allow_offline_reproduction(self):
        cache = self.root / 'labels.json'
        cache.write_text(json.dumps({'queries': {'q': 'TCP'}, 'qrels': {'q': ['1']}}))
        with patch('scripts.datasets.remote', side_effect=AssertionError('Must use cache')):
            self.assertEqual(official_labels(cache), ({'q': 'TCP'}, {'q': {'1'}}))

    def test_public_citations_survive_planning_and_completion_validation(self):
        self.corpus()
        result = self.store.search({'dataset': 'msmarco', 'query': 'TCP'})
        task = {'goal': 'Answer from MS MARCO', 'steps': [{'tool': 'dataset_search', 'result': result}]}
        marker = result['matches'][0]['citation']
        self.assertEqual(document_context(task)['retrieved_evidence'], [result])
        validate_completion(task, {'kind': 'finish', 'summary': 'TCP evidence ' + marker})
        with self.assertRaises(PlanCorrection):
            validate_completion(task, {'kind': 'finish', 'summary': 'Uncited claim'})
        with self.assertRaises(PlanCorrection):
            validate_completion(task, {'kind': 'finish', 'summary': '[S-invented]'})

    def test_capability_requires_web_scope_and_does_not_send_mail(self):
        from intent_kernel.runtime import Runtime
        from tests.test_runtime import ScriptedPlanner
        self.corpus()
        action = {'kind': 'tool', 'summary': 'Search public corpus', 'tool': 'dataset_search', 'arguments': {'dataset': 'msmarco', 'query': 'TCP'}}
        with patch('services.connections.CredentialStore.get', return_value={}):
            kernel = Runtime(Config(self.root), ScriptedPlanner(action))
        try:
            ident = kernel.submit('Search public MS MARCO for TCP', scopes=['files'])['id']
            kernel.tick()
            self.assertEqual(kernel.tasks[ident]['state'], 'APPROVAL')
            self.assertEqual(kernel.tasks[ident]['steps'], [])
            result = kernel.registry.execute(action, {'scopes': ['web'], 'roots': []})
            self.assertEqual(result['matches'][0]['record_id'], '1')
            self.assertFalse(kernel.registry.tools['dataset_search']['writes'])
        finally:
            kernel.close()

    def test_http_catalog_search_and_session_boundary(self):
        import threading
        import urllib.request
        import urllib.error
        from api.server import make_server
        from intent_kernel.runtime import Runtime
        self.corpus()
        with patch('services.connections.CredentialStore.get', return_value={}):
            kernel = Runtime(Config(self.root))
        server = make_server(kernel, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def post(data, token=''):
            return opener.open(urllib.request.Request(base + '/api/datasets/search', json.dumps(data).encode(),
                               {'Content-Type': 'application/json', 'X-IntentOS-Token': token}), timeout=3)
        try:
            catalog = json.load(opener.open(base + '/api/datasets'))
            self.assertEqual(catalog['datasets'][0]['installed']['records'], 3)
            with self.assertRaises(urllib.error.HTTPError) as denied:
                post({'dataset': 'msmarco', 'query': 'TCP'})
            self.assertEqual(denied.exception.code, 403)
            denied.exception.close()
            token = json.load(opener.open(base + '/api/session'))['token']
            result = json.load(post({'dataset': 'msmarco', 'query': 'TCP'}, token))
            self.assertEqual(result['matches'][0]['record_id'], '1')
            with self.assertRaises(urllib.error.HTTPError) as bad:
                post({'dataset': '../private', 'query': 'TCP'}, token)
            self.assertEqual(bad.exception.code, 400)
            bad.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
            kernel.close()


if __name__ == '__main__':
    unittest.main()
