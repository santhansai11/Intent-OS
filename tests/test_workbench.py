"""Workbench permissions, RAG evidence, uploads and scheduling; no real email."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from intent_kernel.config import Config
from intent_kernel.runtime import Runtime
from services.contracts import validate_completion
from services.knowledge import chunks
from services.summary_policy import PlanCorrection


class Workbench(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.temp.name) / 'runtime')
        self.config.values['execution'] = {'workers': 4, 'read_slots': 2, 'model_slots': 2, 'adaptive': False}
        with patch('services.connections.CredentialStore.get', return_value={}):
            self.kernel = Runtime(self.config)
        self.root = self.config.workspace

    def tearDown(self):
        self.kernel.close()
        self.temp.cleanup()

    def task(self, goal='Read these notes', **kwargs):
        return self.kernel.tasks[self.kernel.submit(goal, **kwargs)['id']]

    def file(self, name, content):
        p = self.root / name
        p.write_text(content, encoding='utf-8')
        return p

    def upload(self, name='notes.txt', content=b'Networking notes'):
        return self.kernel.uploads.receive(io.BytesIO(content), name, len(content))

    def test_upload_is_scoped_to_exact_intent(self):
        a = self.upload()
        first = self.task(attachments=[{'id': a['id'], 'role': 'reference'}])
        second = self.task()
        self.assertEqual(self.kernel.registry.read({'path': a['path']}, first)['content'], 'Networking notes')
        with self.assertRaises(ValueError):
            self.kernel.registry.read({'path': a['path']}, second)
        with self.assertRaises(ValueError):
            self.kernel.registry.path(str(Path(a['path']).parent / 'upload.json'), first)

    def test_upload_bounds_cleanup_and_credentials(self):
        for name in ('run.exe', 'credentials.json', '.env', 'passwords.txt'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.upload(name)
        with self.assertRaises(ValueError):
            self.kernel.uploads.receive(io.BytesIO(b'too short'), 'partial.txt', 100)
        self.assertEqual(list(self.kernel.uploads.root.iterdir()), [])
        with self.assertRaises(ValueError):
            self.kernel.uploads.receive(io.BytesIO(b'x'), 'big.txt', 100_000_001)

    def test_history_delete_preserves_originals_and_shared_upload(self):
        original = self.file('original.txt', 'Preserve me')
        a = self.upload()
        one, two = self.task(attachments=[{'id': a['id']}]), self.task(attachments=[{'id': a['id']}])
        for t in (one, two):
            t['state'] = 'COMPLETED'; self.kernel._save(t, 'test', 'done')
        self.kernel.delete_history([one['id']], True)
        self.assertTrue(Path(a['path']).exists())
        self.kernel.delete_history([two['id']], True)
        self.assertFalse(Path(a['path']).exists())
        self.assertEqual(original.read_text(), 'Preserve me')
        self.assertEqual(self.kernel.db.execute('SELECT COUNT(*) FROM events WHERE intent_id=?',(one['id'],)).fetchone()[0],0)

    def test_active_history_and_dependency_deletion_refused(self):
        one = self.task()
        with self.assertRaises(ValueError):
            self.kernel.delete_history([one['id']])
        one['state']='COMPLETED'
        self.task(depends_on=[one['id']])
        with self.assertRaisesRegex(ValueError, 'depend'):
            self.kernel.delete_history([one['id']])

    def test_dependency_waits_until_actual_completion(self):
        one = self.task(); one['state']='PAUSED'
        two = self.task(depends_on=[one['id']])
        self.assertIsNone(self.kernel._choose())
        one['state']='COMPLETED'
        self.assertEqual(self.kernel._choose()['id'],two['id'])

    def test_read_slots_exclude_writes_and_models_have_separate_slots(self):
        t=self.task()
        self.kernel.locks['local-model']='other'
        self.assertEqual(self.kernel.resource_slot(t),'local-model:1')
        t['pending']={'tool':'files_read','arguments':{}}
        self.kernel.locks['filesystem-read:0']='other'
        self.assertEqual(self.kernel.resource_slot(t),'filesystem-read:1')
        t['pending']={'tool':'files_write','arguments':{}}
        self.assertIsNone(self.kernel.resource_slot(t))
        self.kernel.locks={'filesystem':'writer'}
        t['pending']={'tool':'files_read','arguments':{}}
        self.assertIsNone(self.kernel.resource_slot(t))

    def test_memory_pressure_limits_new_dispatch(self):
        self.config.values['execution']['adaptive']=True
        t=self.task()
        with patch('psutil.virtual_memory') as memory:
            memory.return_value.percent=95
            self.kernel.locks={'local-model':'other'}
            self.assertIsNone(self.kernel.resource_slot(t))

    def test_incremental_index_search_and_stale_exclusion(self):
        p=self.file('networks.txt','Reliable transport uses acknowledgements and retransmissions. TCP controls congestion.')
        t=self.task(); index=self.kernel.registry.knowledge
        self.assertFalse(index.index_file(p,t))
        self.assertTrue(index.index_file(p,t))
        result=index.search({'query':'retransmissions'},t)
        self.assertEqual(result['matches'][0]['path'],str(p))
        self.assertTrue(result['matches'][0]['citation'].startswith('[S-'))
        p.write_text('The file has changed and must be indexed again.')
        result=index.search({'query':'retransmissions'},t)
        self.assertEqual(result['matches'],[])
        self.assertEqual(result['stale_files_excluded'],1)

    def test_index_never_exposes_ungranted_uploaded_text(self):
        a=self.upload(content=b'Unique classified dragonfruit')
        permitted=self.task(attachments=[{'id':a['id']}])
        index=self.kernel.registry.knowledge
        index.index_file(Path(a['path']),permitted)
        self.assertTrue(index.search({'query':'dragonfruit'},permitted)['matches'])
        self.assertEqual(index.search({'query':'dragonfruit'},self.task())['matches'],[])

    def test_hybrid_search_fuses_local_vectors(self):
        p=self.file('transport.txt','Reliable delivery confirms received packets.')
        self.config.values['embedding_model']='local-test'
        index=self.kernel.registry.knowledge; t=self.task()
        with patch.object(index,'embed',side_effect=lambda texts:[[1.0,0.0] for _ in texts]):
            index.index_file(p,t)
            result=index.search({'query':'acknowledgements'},t)
        self.assertEqual(result['matches'][0]['path'],str(p))
        self.assertIn('hybrid',result['retrieval'])

    def test_remote_embedding_alias_is_rejected_before_content(self):
        self.config.values['embedding_model']='innocent-alias'
        with patch('services.knowledge.request_json',return_value={'remote_host':'https://example.com'}) as request:
            with self.assertRaisesRegex(Exception,'Cloud embedding'):
                self.kernel.registry.knowledge.embed(['Private source text'])
            request.assert_called_once()
            self.assertNotIn('Private source',str(request.call_args))

    def test_index_job_resumes_and_reports_skips(self):
        self.file('good.txt','Passage about operating systems scheduling.')
        self.file('binary.txt','a\x00binary')
        (self.root/'node_modules').mkdir()
        (self.root/'node_modules'/'hidden.txt').write_text('Do not index')
        t=self.task();t['pending']={'id':'index-job'}
        for _ in range(10):
            result=self.kernel.registry.knowledge.batch({'path':str(self.root)},t)
            if result['status']=='indexed':break
        self.assertEqual(result['status'],'indexed')
        self.assertEqual(result['extracted'],1)
        self.assertEqual(result['skipped_or_unreadable'],1)
        again=self.kernel.registry.knowledge.batch({'path':str(self.root)},t)
        self.assertEqual(again['extracted'],1)

    def test_reference_and_citation_contracts(self):
        a=self.upload();t=self.task(attachments=[{'id':a['id'],'role':'reference'}])
        finish={'kind':'finish','summary':'A draft without a source','arguments':{}}
        with self.assertRaisesRegex(PlanCorrection,'attachments'):
            validate_completion(t,finish)
        t['steps']=[{'tool':'files_read','result':{'path':a['path'],'content':'A reference','truncated':False}}, {'tool':'knowledge_search','result':{'matches':[{'citation':'[S-12345678]'}]}}]
        with self.assertRaisesRegex(PlanCorrection,'Cite'):
            validate_completion(t,finish)
        finish['summary']='Supported content [S-12345678]'
        validate_completion(t,finish)
        finish['summary']='Unknown source [S-00000000]'
        with self.assertRaisesRegex(PlanCorrection,'unknown'):
            validate_completion(t,finish)

    def test_chunks_overlap_without_dropping_tail(self):
        text='alpha '*500+'unique final statement'
        result=list(chunks(text))
        self.assertGreater(len(result),1)
        self.assertTrue(result[-1][2].endswith('unique final statement'))
        self.assertLess(result[1][1],len(result[0][2]))

    def test_reference_requires_contiguous_chunks_and_all_ocr_pages(self):
        a=self.upload();t=self.task(attachments=[{'id':a['id'],'role':'reference'}])
        finish={'kind':'finish','summary':'Complete draft'}
        t['steps']=[{'tool':'files_read','result':{'path':a['path'],'content':'tail','offset':100,'truncated':False}}]
        with self.assertRaises(PlanCorrection):validate_completion(t,finish)
        t['steps'].append({'tool':'files_read','result':{'path':a['path'],'content':'start','offset':0,'next_offset':100,'truncated':True}})
        validate_completion(t,finish)
        t['steps']=[{'tool':'files_ocr','result':{'path':a['path'],'content':'page 2','page':2,'pages':2,'next_page':None}}]
        with self.assertRaises(PlanCorrection):validate_completion(t,finish)
        t['steps'].append({'tool':'files_ocr','result':{'path':a['path'],'content':'page 1','page':1,'pages':2,'next_page':'1'}})
        validate_completion(t,finish)

    def test_short_receipt_after_full_export_is_allowed(self):
        t=self.task('Write at least 5 lines')
        t['steps']=[{'tool':'document_export','arguments':{'content':'one\ntwo\nthree\nfour\nfive'},'result':{'status':'written'}}]
        validate_completion(t,{'kind':'finish','summary':'Saved your document.'})

    def test_parallel_read_batches_respect_global_read_capacity(self):
        batch=self.task();other=self.task()
        batch['pending']={'tool':'files_read_many'}
        other['pending']={'tool':'files_read'}
        self.kernel.locks['filesystem-read:0']=batch['id']
        self.assertIsNone(self.kernel.resource_slot(other))
        self.kernel.locks['filesystem-read:0']=other['id']
        self.assertIsNone(self.kernel.resource_slot(batch))

    def test_invalid_dependency_types_are_rejected(self):
        for value in ([{}], 'bad', False):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.task(depends_on=value)

    def test_grouped_citations_validate_every_marker(self):
        t=self.task()
        t['steps']=[{'tool':'knowledge_search','result':{'matches':[{'citation':'[S-12345678]'},{'citation':'[S-abcdef12]'}]}}]
        validate_completion(t,{'kind':'finish','summary':'Supported claim [S-12345678, S-abcdef12].'})
        with self.assertRaisesRegex(PlanCorrection,'unknown'):
            validate_completion(t,{'kind':'finish','summary':'Claim [S-12345678, S-invented].'})

    def test_http_upload_auth_and_history_lifecycle(self):
        import threading, urllib.request, urllib.error
        from api.server import make_server
        server=make_server(self.kernel,0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def post(path,data,token='',binary=False,origin=None):
            headers={'Content-Type':'application/octet-stream' if binary else 'application/json','X-IntentOS-Token':token,'X-Filename':'notes.txt'}
            if origin:headers['Origin']=origin
            return opener.open(urllib.request.Request(base+path,data if binary else json.dumps(data).encode(),headers),timeout=3)
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:post('/api/uploads',b'notes',binary=True)
            self.assertEqual(error.exception.code,403)
            token=json.load(opener.open(base+'/api/session'))['token']
            with self.assertRaises(urllib.error.HTTPError):post('/api/uploads',b'notes',token,True,'https://example.com')
            self.assertEqual(list(self.kernel.uploads.root.iterdir()),[])
            uploaded=json.load(post('/api/uploads',b'notes',token,True))
            task=json.load(post('/api/intents',{'text':'Read uploaded notes','attachments':[{'id':uploaded['id']}]},token))
            with self.assertRaises(urllib.error.HTTPError):post('/api/uploads/remove',{'id':uploaded['id']},token)
            post(f"/api/intents/{task['id']}/cancel",{},token)
            post('/api/history/delete',{'ids':[task['id']],'remove_uploads':True},token)
            self.assertNotIn(task['id'],self.kernel.tasks)
            self.assertFalse(Path(uploaded['path']).exists())
        finally:
            server.shutdown();server.server_close();thread.join(2)
