"""Executable teaching VM. Time is virtual CPU ticks, never host milliseconds.

One instruction or demand-page fault consumes one tick. The scheduler checks
arrivals, I/O completions, priority and quantum BEFORE every tick. Context lives
in PCBs while off CPU; memory accesses go through private page tables and LRU
physical frames. No AI, network calls or user files are involved.
"""
import copy
import threading

from intent_kernel.dispatch import PRIORITY, strict_pick


def process(pid, priority, program, arrival=0):
    return dict(id=pid, priority=priority, program=program, arrival=arrival)


def scenarios():
    return {
        'priority': [process('P1', 'LOW', [('ADD', 1)] * 5),
                     process('P2', 'HIGH', [('ADD', 2)] * 5),
                     process('P3', 'NORMAL', [('ADD', 3)] * 5)],
        'preemption': [process('P1', 'LOW', [('ADD', 1)] * 6),
                       process('P2', 'HIGH', [('ADD', 10), ('IO', 3), ('ADD', 10), ('ADD', 10)], 2),
                       process('P3', 'NORMAL', [('ADD', 3)] * 6, 1)],
        'round_robin': [process(f'P{i}', 'NORMAL', [('ADD', i)] * 5) for i in (1, 2, 3)],
        'memory_ipc': [
            process('P1', 'LOW', [('WRITE', 0, 11), ('SEND', 'P2', 42), ('READ', 0), ('READ', 99)]),
            process('P2', 'HIGH', [('RECV',), ('WRITE', 0, 21), ('WRITE', 4, 22), ('WRITE', 8, 23),
                                   ('WRITE', 12, 24), ('READ', 0), ('READ', 4), ('READ', 8), ('READ', 12)]),
            process('P3', 'NORMAL', [('WRITE', 0, 31), ('IO', 2), ('READ', 0)]),
        ],
    }


class OSLab:
    PAGE_SIZE = 4
    PAGES = 4

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self, scenario='preemption', quantum=2, frames=3):
        if not isinstance(scenario, str) or scenario not in scenarios():
            raise ValueError('Choose a known OS Lab scenario')
        if type(quantum) is not int or not 1 <= quantum <= 8 or type(frames) is not int or not 1 <= frames <= 8:
            raise ValueError('Use 1–8 ticks per quantum and 1–8 physical frames')
        with self.lock:
            self.scenario, self.quantum = scenario, quantum
            self.time, self.queue_seq, self.slice_used = 0, 0, 0
            self.current, self.previous = None, None
            self.cpu = {'pc': 0, 'acc': 0}
            self.tasks = {}
            self.frames = [None] * frames
            self.backing = {}
            self.events, self.timeline = [], []
            self.switches, self.faults, self.evictions, self.clock = 0, 0, 0, 0
            for p in scenarios()[scenario]:
                self.tasks[p['id']] = {**p, 'state': 'NEW', 'pc': 0, 'acc': 0, 'cpu_ticks': 0,
                    'wait_ticks': 0, 'blocked_ticks': 0, 'response': None, 'completed_at': None,
                    'page_table': {}, 'inbox': [], 'received': [], 'reads': [], 'error': ''}
                self.backing[p['id']] = [bytearray(self.PAGE_SIZE) for _ in range(self.PAGES)]
            self._event('reset', None, f'{scenario}: strict priority, quantum {quantum} ticks, {frames} frames')
            return self.snapshot()

    def _event(self, kind, pid, message, **details):
        self.events.append(dict(seq=len(self.events) + 1, tick=self.time, kind=kind, pid=pid,
                                message=message, **details))

    def _ready(self, p):
        self.queue_seq += 1
        p['state'], p['queue_order'] = 'READY', self.queue_seq

    def _save_cpu(self):
        if self.current:
            self.tasks[self.current].update(self.cpu)

    def _leave(self, reason, ready=True):
        p = self.tasks[self.current]
        self._save_cpu()
        self._event('context_save', p['id'], reason, registers=dict(self.cpu), slice_used=self.slice_used)
        if ready:
            self._ready(p)
        self.previous, self.current, self.slice_used = self.current, None, 0

    def _free(self, p):
        for idx in p['page_table'].values():
            self.frames[idx] = None
        p['page_table'] = {}
        self.backing.pop(p['id'], None)
        self._event('memory_release', p['id'], 'Released resident frames and private backing pages')

    def _access(self, p, address, write=None):
        if type(address) is not int or not 0 <= address < self.PAGE_SIZE * self.PAGES:
            raise ValueError(f'Protection fault: address {address} outside private address space 0–15')
        page, offset = divmod(address, self.PAGE_SIZE)
        if page not in p['page_table']:
            self.faults += 1
            index = next((i for i, f in enumerate(self.frames) if f is None), None)
            if index is None:
                index = min(range(len(self.frames)), key=lambda i: self.frames[i]['last_used'])
                old = self.frames[index]
                self.backing[old['pid']][old['page']] = bytearray(old['data'])
                del self.tasks[old['pid']]['page_table'][old['page']]
                self.evictions += 1
                self._event('evict', old['pid'], f'LRU: page {old["page"]} → backing store; frame {index} reused')
            self.clock += 1
            self.frames[index] = dict(pid=p['id'], page=page, data=bytearray(self.backing[p['id']][page]), last_used=self.clock)
            p['page_table'][page] = index
            self._event('page_fault', p['id'], f'Page {page} loaded into frame {index}; retry instruction next tick')
            return False, None
        index = p['page_table'][page]
        frame = self.frames[index]
        assert frame['pid'] == p['id'] and frame['page'] == page
        self.clock += 1
        frame['last_used'] = self.clock
        if write is not None:
            frame['data'][offset] = write
        self._event('memory_access', p['id'], f'Virtual {address} → physical {index * self.PAGE_SIZE + offset}',
                    value=frame['data'][offset], write=write is not None)
        return True, frame['data'][offset]

    def step(self):
        with self.lock:
            if self.done:
                return self.snapshot()
            if self.time >= 500:
                raise ValueError('Lab reached its 500-tick safety limit; reset to continue')
            for p in self.tasks.values():
                if p['state'] == 'NEW' and p['arrival'] <= self.time:
                    self._ready(p)
                    self._event('admit', p['id'], f'{p["priority"]} priority admitted')
                elif p['state'] == 'BLOCKED_IO' and p['wake_at'] <= self.time:
                    self._ready(p)
                    self._event('wake', p['id'], 'I/O completed; returned to ready queue')
            ready = [p for p in self.tasks.values() if p['state'] == 'READY']
            best = strict_pick(ready, lambda p: p['queue_order'])
            if self.current:
                running = self.tasks[self.current]
                if best and PRIORITY[best['priority']] < PRIORITY[running['priority']]:
                    self._leave(f'Higher-priority {best["id"]} is ready')
                elif self.slice_used >= self.quantum:
                    self._leave('Time quantum expired; requeue behind equal-priority peers')
            if not self.current:
                ready = [p for p in self.tasks.values() if p['state'] == 'READY']
                best = strict_pick(ready, lambda p: p['queue_order'])
                if best:
                    self.current = best['id']
                    self.cpu = {k: best[k] for k in ('pc', 'acc')}
                    best['state'] = 'RUNNING'
                    if best['response'] is None:
                        best['response'] = self.time - best['arrival']
                    if self.previous and self.previous != self.current:
                        self.switches += 1
                    self._event('dispatch', self.current, 'Highest ready priority; FIFO rotation among equals',
                                previous=self.previous, registers=dict(self.cpu))
            self._event('schedule_check', self.current, 'Priority and quantum checked before this tick',
                        ready=[p['id'] for p in sorted(self.tasks.values(), key=lambda p: p.get('queue_order', 0)) if p['state'] == 'READY'],
                        slice_used=self.slice_used, quantum=self.quantum)
            for p in self.tasks.values():
                if p['state'] == 'READY':
                    p['wait_ticks'] += 1
                elif p['state'].startswith('BLOCKED'):
                    p['blocked_ticks'] += 1
            if not self.current:
                self.timeline.append(dict(tick=self.time, pid=None, operation='IDLE'))
                self.time += 1
                return self.snapshot()
            p = self.tasks[self.current]
            ins = p['program'][self.cpu['pc']]
            op, args = ins[0], ins[1:]
            before = dict(self.cpu)
            advance, blocked, fault = True, None, False
            try:
                if op == 'ADD':
                    self.cpu['acc'] += args[0]
                elif op in ('WRITE', 'READ'):
                    advance, value = self._access(p, args[0], args[1] if op == 'WRITE' else None)
                    fault = not advance
                    if advance and op == 'READ':
                        self.cpu['acc'] = value
                        p['reads'].append(dict(address=args[0], value=value))
                elif op == 'IO':
                    blocked = 'BLOCKED_IO'
                    p['wake_at'] = self.time + 1 + args[0]
                elif op == 'SEND':
                    target = self.tasks[args[0]]
                    target['inbox'].append(args[1])
                    self._event('ipc_send', p['id'], f'Sent {args[1]} to {target["id"]}')
                    if target['state'] == 'BLOCKED_IPC':
                        self._ready(target)
                        self._event('wake', target['id'], 'Message arrived; receive can resume')
                elif op == 'RECV':
                    if p['inbox']:
                        self.cpu['acc'] = p['inbox'].pop(0)
                        p['received'].append(self.cpu['acc'])
                        self._event('ipc_receive', p['id'], f'Received {self.cpu["acc"]}')
                    else:
                        advance, blocked = False, 'BLOCKED_IPC'
                else:
                    raise ValueError('Unknown VM instruction')
                if advance:
                    self.cpu['pc'] += 1
            except ValueError as exc:
                p['state'], p['error'] = 'FAILED', str(exc)
                self._event('protection_fault', p['id'], str(exc))
            p['cpu_ticks'] += 1
            self.slice_used += 1
            self._save_cpu()
            self.timeline.append(dict(tick=self.time, pid=p['id'], operation='PAGE FAULT' if fault else op,
                                      before=before, after=dict(self.cpu), slice_used=self.slice_used))
            self.time += 1
            if p['state'] == 'FAILED' or self.cpu['pc'] >= len(p['program']):
                if p['state'] != 'FAILED':
                    p['state'] = 'COMPLETED'
                p['completed_at'] = self.time
                self._leave(p['state'], ready=False)
                self._free(p)
                self._event('exit', p['id'], p['state'])
            elif blocked:
                p['state'] = blocked
                self._leave('Waiting for I/O' if blocked == 'BLOCKED_IO' else 'Waiting for a message', ready=False)
            return self.snapshot()

    @property
    def done(self):
        return all(p['state'] in ('COMPLETED', 'FAILED') for p in self.tasks.values())

    def snapshot(self):
        with self.lock:
            deadlocked = not self.current and any(p['state'] == 'BLOCKED_IPC' for p in self.tasks.values()) and all(
                p['state'] in ('BLOCKED_IPC', 'COMPLETED', 'FAILED') for p in self.tasks.values())
            return copy.deepcopy(dict(scenario=self.scenario, tick=self.time, quantum=self.quantum,
                current=self.current, cpu=self.cpu if self.current else None, slice_used=self.slice_used,
                done=self.done, deadlocked=deadlocked, processes=list(self.tasks.values()),
                ready=[p['id'] for p in sorted(self.tasks.values(), key=lambda p: (PRIORITY[p['priority']], p.get('queue_order', 0))) if p['state'] == 'READY'],
                frames=[{**f, 'data': list(f['data'])} if f else None for f in self.frames],
                memory=dict(page_size=self.PAGE_SIZE, virtual_bytes_per_process=self.PAGE_SIZE*self.PAGES,
                            resident_bytes=sum(f is not None for f in self.frames)*self.PAGE_SIZE,
                            capacity_bytes=len(self.frames)*self.PAGE_SIZE,
                            backing_bytes=len(self.backing)*self.PAGE_SIZE*self.PAGES),
                metrics=dict(context_switches=self.switches, page_faults=self.faults, evictions=self.evictions,
                             busy_ticks=sum(t['pid'] is not None for t in self.timeline)),
                timeline=self.timeline, events=self.events))
