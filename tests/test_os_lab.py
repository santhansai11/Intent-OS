"""Scheduler outcomes and memory integrity, independent of models and Google APIs."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from api.server import make_server
from intent_kernel.config import Config
from intent_kernel.os_lab import OSLab
from intent_kernel.runtime import Runtime
from tests.test_runtime import ScriptedPlanner, finish


def drain(lab):
    for _ in range(500):
        state = lab.snapshot()
        if state['done'] or state['deadlocked']:
            return state
        lab.step()
    raise AssertionError('Scheduler did not finish')


class LabTests(unittest.TestCase):
    def test_strict_priority_does_not_rotate_into_lower_queue(self):
        lab = OSLab()
        lab.reset('priority', 2)
        state = drain(lab)
        self.assertEqual([t['pid'] for t in state['timeline']], ['P2']*5 + ['P3']*5 + ['P1']*5)
        self.assertEqual([p['acc'] for p in state['processes']], [5, 10, 15])
        self.assertEqual(state['metrics']['context_switches'], 2)
        self.assertEqual([p['wait_ticks'] for p in state['processes']], [10, 0, 5])

    def test_higher_arrival_and_io_wakeup_preempt_before_next_instruction(self):
        lab = OSLab()
        state = drain(lab)
        self.assertEqual([t['pid'] for t in state['timeline'][:9]], ['P1','P3','P2','P2','P3','P3','P3','P2','P2'])
        saves = [e for e in state['events'] if e['kind']=='context_save' and 'Higher-priority' in e['message']]
        self.assertEqual([(e['tick'], e['pid']) for e in saves], [(1,'P1'), (2,'P3'), (7,'P3')])
        self.assertEqual([p['acc'] for p in state['processes']], [6,30,18])
        self.assertEqual(next(p for p in state['processes'] if p['id']=='P2')['blocked_ticks'], 3)

    def test_equal_priority_quantum_and_context_restore(self):
        lab = OSLab()
        lab.reset('round_robin', 2)
        state = drain(lab)
        self.assertEqual([t['pid'] for t in state['timeline']], ['P1','P1','P2','P2','P3','P3']*2+['P1','P2','P3'])
        self.assertEqual([p['acc'] for p in state['processes']], [5,10,15])
        for pid in ('P1','P2','P3'):
            self.assertEqual([t['before']['pc'] for t in state['timeline'] if t['pid']==pid], list(range(5)))

    def test_quantum_one_and_large_quantum(self):
        for q in (1, 3, 8):
            lab=OSLab()
            lab.reset('round_robin',q)
            state=drain(lab)
            self.assertTrue(all(t['slice_used']<=q for t in state['timeline']))
            self.assertEqual(state['metrics']['busy_ticks'],15)
            self.assertEqual(len([e for e in state['events'] if e['kind']=='schedule_check']),15)

    def test_paging_preserves_evicted_values_ipc_wakes_and_fault_is_isolated(self):
        lab=OSLab()
        lab.reset('memory_ipc',2,2)
        state=drain(lab)
        tasks={p['id']:p for p in state['processes']}
        self.assertEqual(tasks['P2']['received'],[42])
        self.assertEqual([r['value'] for r in tasks['P2']['reads']],[21,22,23,24])
        self.assertEqual(tasks['P1']['reads'],[{'address':0,'value':11}])
        self.assertEqual(tasks['P3']['reads'],[{'address':0,'value':31}])
        self.assertEqual(tasks['P1']['state'],'FAILED')
        self.assertEqual(tasks['P2']['state'],'COMPLETED')
        self.assertEqual(tasks['P3']['state'],'COMPLETED')
        self.assertGreater(state['metrics']['evictions'],0)
        self.assertEqual(state['memory']['resident_bytes'],0)
        self.assertEqual(state['memory']['backing_bytes'],0)
        self.assertTrue(all(f is None for f in state['frames']))

    def test_private_translation_and_accounting_invariants_each_tick(self):
        for scenario in ('priority','preemption','round_robin','memory_ipc'):
            for q in (1,2,8):
                lab=OSLab();lab.reset(scenario,q,1)
                for _ in range(500):
                    s=lab.step()
                    running=[p for p in s['processes'] if p['state']=='RUNNING']
                    self.assertLessEqual(len(running),1)
                    for p in s['processes']:
                        for page,idx in p['page_table'].items():
                            self.assertEqual((s['frames'][idx]['pid'],s['frames'][idx]['page']),(p['id'],page))
                        if p['completed_at'] is not None:
                            self.assertEqual(p['cpu_ticks']+p['wait_ticks']+p['blocked_ticks'],p['completed_at']-p['arrival'])
                    if s['done']: break
                self.assertTrue(s['done'])

    def test_page_fault_retries_same_instruction_and_lru_replaces_oldest(self):
        lab=OSLab();lab.reset('memory_ipc',2,2)
        p=lab.tasks['P1']
        self.assertFalse(lab._access(p,0,11)[0])
        self.assertTrue(lab._access(p,0,11)[0])
        lab._access(p,4,22);lab._access(p,4,22)
        lab._access(p,0)  # page 0 is now most recently used
        lab._access(p,8)
        self.assertIn(0,p['page_table']);self.assertNotIn(1,p['page_table'])
        self.assertEqual(lab.backing['P1'][1][0],22)

    def test_reset_validation_done_noop_and_snapshot_isolation(self):
        lab=OSLab()
        for args in [('bad',2,3),('priority',0,3),('priority',True,3),('priority',2,9)]:
            with self.assertRaises(ValueError): lab.reset(*args)
        s=lab.snapshot();s['processes'][0]['pc']=999
        self.assertEqual(lab.tasks['P1']['pc'],0)
        done=drain(lab)
        self.assertEqual(lab.step(),done)
        self.assertEqual(lab.reset()['tick'],0)


class RuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.config=Config(Path(self.tmp.name)/'runtime')
        self.keys=patch('services.connections.CredentialStore.get',return_value={});self.keys.start()
        self.rt=Runtime(self.config,ScriptedPlanner(finish(),finish(),finish()),workers=1)

    def tearDown(self):
        self.rt.close();self.keys.stop();self.tmp.cleanup()

    def test_live_runtime_strict_policy_ignores_aging_and_deadline(self):
        self.config.update({'scheduling':'strict_priority'})
        tasks=[self.rt.submit('Test '+p,priority=p) for p in ('LOW','HIGH','NORMAL')]
        low=self.rt.tasks[tasks[0]['id']]
        low['queued_at']=0;low['deadline']=1
        for index in (1,2,0):
            self.assertTrue(self.rt.tick())
            self.assertEqual(self.rt.tasks[tasks[index]['id']]['state'],'COMPLETED')

    def test_real_runtime_equal_priority_rotates_and_skips_blocked(self):
        self.config.update({'scheduling':'strict_priority'})
        one=self.rt.submit('one',priority='HIGH')['id'];two=self.rt.submit('two',priority='HIGH')['id']
        self.assertEqual(self.rt._choose()['id'],one)
        self.rt.tasks[one]['last_dispatch']=99999999999
        self.assertEqual(self.rt._choose()['id'],two)
        self.rt.tasks[two]['state']='BLOCKED'
        self.assertEqual(self.rt._choose()['id'],one)

    def test_http_lab_uses_session_guard_and_never_submits_intents(self):
        server=make_server(self.rt,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_address[1])
        def post(route,payload,token=''):
            req=urllib.request.Request(base+route,json.dumps(payload).encode(),{'Content-Type':'application/json','X-IntentOS-Token':token})
            with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)
        try:
            with self.assertRaises(urllib.error.HTTPError) as err:post('/api/os-lab/step',{})
            self.assertEqual(err.exception.code,403)
            s=post('/api/os-lab/reset',{'scenario':'priority','quantum':1},server.token)
            self.assertEqual(s['tick'],0)
            self.assertEqual(post('/api/os-lab/step',{},server.token)['timeline'][0]['pid'],'P2')
            self.assertEqual(self.rt.tasks,{})
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__': unittest.main()
