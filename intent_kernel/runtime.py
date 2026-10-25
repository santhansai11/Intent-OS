"""Durable userspace intent processes with cooperative scheduling and capability isolation.

A quantum is one model decision OR one tool call. I/O runs outside the kernel lock.
SQLite commits the process checkpoint and audit event together. External effects cannot
be committed atomically with SQLite: interrupted writes require explicit reconciliation.
"""
from __future__ import annotations

import copy
import json
import math
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from intent_kernel.config import Config
from planner.router import PlannerRouter
from services.capabilities import CapabilityRegistry
from services.connections import GoogleConnection

TERMINAL = {'COMPLETED', 'CANCELLED', 'FAILED'}
SCOPES = {'system', 'files', 'web', 'calendar', 'drive', 'gmail', 'maps', 'meet'}


class Runtime:
    def __init__(self, config=None, planner=None, registry=None, workers=None):
        self.config = config or Config()
        self.google = GoogleConnection(self.config)
        self.registry = registry or CapabilityRegistry(self.config, self.google)
        self.planner = planner or PlannerRouter(self.config)
        self.worker_count = workers or self.config.execution['workers']
        self._worker_override = workers
        from services.uploads import UploadStore
        self.uploads = UploadStore(self.config)
        self._host_sample = (0, 0)
        self.cv = threading.Condition(threading.RLock())
        self.stopping = False
        self.threads = []
        self.locks = {}
        self.policy = 'fair queue'
        self.reason = 'Waiting for an intent'
        self.revision = 0
        from intent_kernel.os_lab import OSLab
        self.os_lab = OSLab()
        # OS lock prevents two runtimes from dispatching the same durable process.
        self.lease = (self.config.root / 'kernel.lock').open('a+b')
        self.lease.seek(0)
        try:
            if __import__('os').name == 'nt':
                import msvcrt
                if not self.lease.read(1):
                    self.lease.write(b'0')
                    self.lease.flush()
                self.lease.seek(0)
                msvcrt.locking(self.lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close()
            raise RuntimeError('Another IntentOS kernel is using this data directory') from None
        self.db = sqlite3.connect(self.config.root / 'kernel.sqlite3', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS processes (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT,
                intent_id TEXT NOT NULL, timestamp REAL NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL);
        ''')
        self.tasks = {row[0]: json.loads(row[1]) for row in self.db.execute('SELECT id,data FROM processes')}
        for task in self.tasks.values():
            task.setdefault('provider', 'ollama')
            if (task['state'] == 'REVIEW' and (task.get('pending') or {}).get('tool') == 'gmail_send'
                    and task.get('error', '').startswith('gmail.googleapis.com returned HTTP 403 ')):
                task['state'] = 'BLOCKED'
                task['error'] = 'Gmail rejected the send (HTTP 403); this request was not sent. Enable Gmail API in Google Cloud and check Gmail permissions before resuming.'
                task['history'].append({'action': task['pending'], 'observation': {'status': 'rejected', 'http_status': 403, 'message': task['error']}})
                task['pending'] = None
                self._save(task, 'recovery', 'Classified the recorded Gmail 403 as a rejected request; no automatic retry')
            if task['state'] in ('RUNNING', 'CANCELLING', 'PAUSING'):
                pending = task.get('pending')
                scanning = pending and pending['tool'] == 'files_collect' and self.registry.collections.scan_incomplete(pending['id'])
                if pending and self.registry.tools[pending['tool']]['writes'] and not scanning:
                    task['state'] = 'REVIEW'
                    task['error'] = 'Execution was interrupted. This action may already have happened. Check its destination before retrying.'
                else:
                    task['state'] = 'CANCELLED' if task.get('cancel_requested') else ('PAUSED' if task.get('pause_requested') else 'READY')
                self._save(task, 'recovery', 'Restored from durable checkpoint')

    def _save(self, task, kind, message):
        task['updated_at'] = time.time()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO processes VALUES (?,?)', (task['id'], json.dumps(task)))
            self.db.execute('INSERT INTO events(intent_id,timestamp,kind,message) VALUES (?,?,?,?)',
                            (task['id'], task['updated_at'], kind, message[:2000]))
        self.revision += 1
        # Some initialization paths do not hold the condition yet.
        with self.cv:
            self.cv.notify_all()

    def submit(self, goal, priority='NORMAL', deadline=None, roots=None, scopes=None, access_mode='selected', auto_outputs=False, workflow=None, search_roots=None, output_folder=None, attachments=None, depends_on=None):
        if not isinstance(goal, str) or not goal.strip() or len(goal) > 12000:
            raise ValueError('Enter a goal between 1 and 12000 characters')
        if priority not in ('LOW', 'NORMAL', 'HIGH'):
            raise ValueError('Priority must be LOW, NORMAL or HIGH')
        if deadline:
            if not isinstance(deadline, str):
                raise ValueError('Deadline must be an ISO timestamp with timezone')
            parsed = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('Deadline must include a timezone')
            deadline = parsed.timestamp()
            if not math.isfinite(deadline):
                raise ValueError('Invalid deadline')
        if access_mode not in ('selected', 'system') or not isinstance(auto_outputs, bool):
            raise ValueError('Invalid folder access or output permission')
        roots = roots if roots is not None else self.config.roots
        scopes = scopes if scopes is not None else ['system', 'files']
        if not isinstance(roots, list) or any(not isinstance(r, str) or not Path(r).expanduser().is_absolute() for r in roots):
            raise ValueError('Choose folders from Connections')
        configured = {Path(r).resolve(): r for r in self.config.roots}
        if any(Path(r).expanduser().resolve() not in configured for r in roots):
            raise ValueError('Choose folders from Connections')
        roots = list(dict.fromkeys(configured[Path(r).expanduser().resolve()] for r in roots))
        if access_mode == 'system':
            roots = list(dict.fromkeys([str(self.config.workspace), *self.config.system_roots()]))
            search_roots = self.config.system_roots()
        elif search_roots is not None:
            if not isinstance(search_roots, list) or any(not isinstance(r, str) or not Path(r).expanduser().is_absolute() or Path(r).expanduser().resolve() not in {Path(root) for root in roots} for r in search_roots):
                raise ValueError('Search folders must be among this intent’s granted folders')
            search_roots = list(dict.fromkeys(configured[Path(r).expanduser().resolve()] for r in search_roots))
        if not isinstance(scopes, list) or any(s not in SCOPES for s in scopes):
            raise ValueError('Invalid read grant')
        # The user's explicit destination is a separate, per-goal folder grant.
        # Copy the search list BEFORE adding it, so choosing an output location
        # never expands the folders scanned for source material.
        search_roots = list(roots if search_roots is None else search_roots)
        if output_folder is not None:
            if not isinstance(output_folder, str) or not output_folder.strip() or len(output_folder) > 4096:
                raise ValueError('Enter an absolute Save in folder path')
            chosen = Path(output_folder.strip()).expanduser()
            if not chosen.is_absolute():
                raise ValueError('Save in folder must be an absolute path, for example D:\\meeting')
            chosen = self.registry.path(str(chosen), {'roots': [str(chosen)]})
            ancestor = chosen
            while not ancestor.exists() and ancestor.parent != ancestor:
                ancestor = ancestor.parent
            if not ancestor.is_dir():
                raise ValueError('Save in folder must be a folder on an available drive')
            output_folder = str(chosen)
            roots = list(dict.fromkeys([*roots, output_folder]))
        now = time.time()
        task = {'id': uuid.uuid4().hex, 'goal': goal.strip(), 'state': 'READY',
                'priority': priority, 'deadline': deadline, 'roots': roots, 'scopes': scopes,
                'created_at': now, 'updated_at': now, 'queued_at': now, 'last_dispatch': 0,
                'history': [], 'steps': [], 'pending': None, 'answer': '', 'question': '',
                'error': '', 'attempts': 0, 'retry_at': 0, 'turns': 0, 'max_turns': 48,
                'cancel_requested': False, 'pause_requested': False, 'active': '', 'elapsed_ms': 0}
        task.update({'access_mode': access_mode, 'auto_outputs': auto_outputs, 'provider': self.config.provider,
                     'search_roots': search_roots, 'output_folder': output_folder or str(self.config.workspace)})
        task['attachments'] = self.uploads.resolve(attachments or [])
        dependencies = depends_on if depends_on is not None else []
        if not isinstance(dependencies, list) or len(dependencies) > 10 or any(not isinstance(i, str) or i not in self.tasks for i in dependencies):
            raise ValueError('Choose up to 10 existing dependency intents')
        task['depends_on'] = list(dict.fromkeys(dependencies))
        if task['attachments'] and 'files' not in scopes:
            raise ValueError('Enable Local files to use attachments')
        if workflow is not None:
            if isinstance(workflow, dict) and workflow.get('type') == 'index' and set(workflow) == {'type', 'path'}:
                action = {'kind': 'tool', 'tool': 'knowledge_index', 'summary': 'Build the local knowledge index', 'arguments': {'path': workflow['path']}, 'complete_after': True}
            elif isinstance(workflow, dict) and workflow.get('type') == 'collect' and {'type', 'query', 'destination'} <= set(workflow) and not set(workflow) - {'type', 'query', 'destination', 'modified_after', 'modified_before', 'include_projects'}:
                action = {'kind': 'tool', 'tool': 'files_collect', 'summary': 'Gather related files into a separate folder', 'arguments': {k: v for k, v in workflow.items() if k != 'type'}, 'complete_after': True}
                self.registry.collections.terms(workflow['query'])
                from services.search_query import search_spec
                search_spec(workflow)
            else:
                raise ValueError('Unknown direct workflow')
            self.registry.validate(action, task)
            allowed = (workflow['type'] == 'index' or auto_outputs) and 'files' in scopes
            task['pending'] = {**action, 'id': uuid.uuid4().hex, 'approved': allowed}
            task['state'] = 'READY' if allowed else 'APPROVAL'
        with self.cv:
            if sum(t['state'] not in TERMINAL for t in self.tasks.values()) >= 100:
                raise ValueError('The queue has 100 unfinished intents; finish or cancel some first')
            self.tasks[task['id']] = task
            self._save(task, 'admitted', 'Intent admitted with explicit folder and read grants')
            return copy.deepcopy(task)

    def _choose(self):
        now = time.time()
        available = []
        for task in self.tasks.values():
            if task['state'] not in ('READY', 'RECOVERY') or task['retry_at'] > now:
                continue
            if any(self.tasks.get(i, {}).get('state') != 'COMPLETED' for i in task.get('depends_on', [])):
                continue
            if self.resource_slot(task) is not None:
                available.append(task)
        if not available:
            return None
        if self.config.scheduling == 'strict_priority':
            from intent_kernel.dispatch import strict_pick
            self.policy, self.reason = 'strict priority + round robin', 'Highest runnable priority at each call boundary; no aging or deadline override'
            return strict_pick(available, lambda t: (t['last_dispatch'], t['created_at'], t['id']))
        starved = [t for t in available if now - t['queued_at'] >= 30]
        dated = [t for t in available if t['deadline'] and t['deadline'] - now < 43200]
        if starved:
            selected = min(starved, key=lambda t: t['queued_at'])
            self.policy, self.reason = 'aging', 'A waiting intent receives a quantum to prevent starvation'
        elif dated:
            selected = min(dated, key=lambda t: (t['deadline'], t['last_dispatch']))
            self.policy, self.reason = 'earliest deadline', 'The nearest deadline receives the next available quantum'
        else:
            selected = min(available, key=lambda t: ({'HIGH': 0, 'NORMAL': 1, 'LOW': 2}[t['priority']], t['last_dispatch'], t['created_at']))
            self.policy, self.reason = 'priority + round robin', 'Highest priority first; equal priorities alternate at each checkpoint'
        return selected

    def resource_slot(self, task):
        """Bounded read/model concurrency; file writes exclude all file readers."""
        execution = self.config.execution
        limit = self._worker_override or execution['workers']
        if execution['adaptive']:
            now = time.monotonic()
            if now - self._host_sample[0] > 5:
                try:
                    import psutil
                    self._host_sample = (now, psutil.virtual_memory().percent)
                except ImportError:
                    self._host_sample = (now, 0)
            if self._host_sample[1] >= 90:
                limit = 1
        if len(self.locks) >= limit:
            return None
        action = task.get('pending')
        base = self.registry.resource(action)
        if action is None:
            # Keep the old resource identity for the first slot.
            names = ['local-model'] + [f'local-model:{i}' for i in range(1, execution['model_slots'])]
        elif base == 'filesystem' and not self.registry.tools[action['tool']]['writes']:
            if 'filesystem' in self.locks:
                return None
            readers = [owner for key, owner in self.locks.items() if key.startswith('filesystem-read:')]
            # A read-many action uses its own bounded pool: reserve the read lane
            # so several such pools cannot multiply the configured concurrency.
            if readers and (action['tool'] == 'files_read_many' or any((self.tasks.get(owner, {}).get('pending') or {}).get('tool') == 'files_read_many' for owner in readers)):
                return None
            names = [f'filesystem-read:{i}' for i in range(execution['read_slots'])]
        else:
            if base == 'filesystem' and any(k.startswith('filesystem-read:') for k in self.locks):
                return None
            names = [base]
        return next((name for name in names if name not in self.locks), None)

    def delete_history(self, ids, remove_uploads=False):
        if not isinstance(ids, list) or not ids or len(ids) > 1000 or any(not isinstance(i, str) for i in ids):
            raise ValueError('Choose completed intents to delete')
        with self.cv:
            targets = [self.tasks[i] for i in set(ids) if i in self.tasks]
            if any(t['state'] not in TERMINAL for t in targets):
                raise ValueError('Cancel or complete active intents before deleting their history')
            if any(set(t.get('depends_on', [])) & set(ids) for t in self.tasks.values() if t['id'] not in ids):
                raise ValueError('Other intents depend on this history. Delete their history first.')
            candidates = {a['id'] for t in targets for a in t.get('attachments', [])}
            retained = {a['id'] for t in self.tasks.values() if t['id'] not in ids for a in t.get('attachments', [])}
            with self.db:
                for t in targets:
                    self.db.execute('DELETE FROM events WHERE intent_id=?', (t['id'],))
                    self.db.execute('DELETE FROM processes WHERE id=?', (t['id'],))
            for t in targets:
                del self.tasks[t['id']]
            self.revision += 1
            self.cv.notify_all()
            if remove_uploads:
                for ident in candidates - retained:
                    self.registry.knowledge.forget([self.uploads.resolve([{'id': ident}])[0]['path']])
                    self.uploads.remove(ident)
            return {'deleted': len(targets), 'original_files_preserved': True}

    def tick(self):
        """Dispatch one quantum. Also usable synchronously in deterministic tests."""
        with self.cv:
            if self.stopping:
                return False
            task = self._choose()
            if not task:
                return False
            resource = self.resource_slot(task)
            self.locks[resource] = task['id']
            task['state'] = 'RUNNING'
            task['last_dispatch'] = time.time()
            task['active'] = task['pending']['tool'] if task['pending'] else 'Planning next action'
            self._save(task, 'dispatch', task['active'])
            snapshot = copy.deepcopy(task)
            snapshot['connections'] = self.google.status()
        start = time.monotonic()
        try:
            pending = snapshot['pending']
            if pending:
                # Authorization is checked at the dispatch boundary, independently of the model.
                spec = self.registry.validate(pending, snapshot)
                if pending.get('authorization') == 'explicit_email_request':
                    from services.mail_policy import authorize_send
                    if not authorize_send(snapshot, pending):
                        raise ValueError('The email no longer matches the user request; review before sending')
                if not pending.get('approved') and (spec['writes'] or spec['scope'] not in snapshot['scopes']):
                    raise ValueError('This capability has no approval')
                result = self.registry.execute(pending, snapshot)
                outcome = ('progress' if pending['tool'] in ('files_collect', 'files_find_related', 'knowledge_index') and isinstance(result, dict) and result.get('status') == 'scanning' else 'result', result)
            else:
                action = self.planner.decide(snapshot, self.registry.catalog())
                from services.contracts import validate_completion, attachment_continuation
                from services.summary_policy import PlanCorrection
                try:
                    validate_completion(snapshot, action)
                except PlanCorrection:
                    continuation = attachment_continuation(snapshot)
                    if continuation is None:
                        raise
                    action = continuation
                if action['kind'] == 'ask':
                    import re
                    if re.search(r'\b(?:password|app password|client secret|access token|authorization code)\b', action.get('summary', ''), re.I):
                        from services.connections import ConnectionError
                        raise ConnectionError('Account authentication belongs in Connections. Gmail uses Google sign-in; never enter your password in intent chat.')
                if action['kind'] == 'tool':
                    self.registry.validate(action, snapshot)
                outcome = ('action', action)
        except Exception as exc:
            outcome = ('error', exc)
        with self.cv:
            self.locks.pop(resource, None)
            task['elapsed_ms'] += round((time.monotonic() - start) * 1000)
            task['active'] = ''
            task['queued_at'] = time.time()
            kind, value = outcome
            if kind == 'error':
                task['error'] = str(value)[:1500]
                task['attempts'] += 1
                pending = task['pending']
                if not pending:
                    task['history'].append({'planner_error': task['error'],
                                            'instruction': 'Correct the next action using the capability schema.'})
                from services.summary_policy import PlanCorrection
                if isinstance(value, PlanCorrection):
                    if pending:
                        task['history'].append({'planner_error': task['error'], 'instruction': 'Correct the next action; no external action was attempted.'})
                    task['pending'] = None
                    task['state'] = 'RECOVERY' if task['attempts'] < 3 else 'BLOCKED'
                    task['retry_at'] = time.time() + 2 ** task['attempts'] if task['state'] == 'RECOVERY' else 0
                elif pending and pending['tool'] in ('gmail_send', 'gmail_draft', 'drive_create_folder', 'drive_upload') and getattr(value, 'request_rejected', False):
                    task['state'] = 'BLOCKED'
                    task['error'] += (' Gmail rejected this request; it was not sent or saved.' if pending['tool'].startswith('gmail_') else ' Drive rejected this request; the folder or file was not created.')
                    task['history'].append({'action': pending, 'observation': {'status': 'rejected', 'http_status': value.status, 'message': task['error']}})
                    task['pending'] = None
                elif pending and self.registry.tools[pending['tool']]['writes']:
                    task['state'] = 'REVIEW'
                    task['error'] += ' The action may have partially completed. Check the destination before retrying.'
                elif getattr(value, 'retryable', False) and task['attempts'] < 3:
                    task['state'] = 'RECOVERY'
                    task['retry_at'] = time.time() + max(2 ** task['attempts'], getattr(value, 'retry_after', 0))
                else:
                    task['state'] = 'BLOCKED'
                self._save(task, 'error', task['error'])
            elif kind == 'progress':
                task['scan_progress'] = value
                task['state'], task['error'], task['attempts'] = 'READY', '', 0
                self._save(task, 'scan_progress', f"Scan {value['phase']}: {value['scanned']} files discovered, {value['extracted']} contents checked, {value['matched']} matches so far")
            elif kind == 'result':
                task.pop('scan_progress', None)
                pending = task['pending']
                step = {**pending, 'result': value, 'completed_at': time.time()}
                task['steps'].append(step)
                task['history'].append({'action': {k: pending[k] for k in ('tool', 'arguments', 'summary')}, 'observation': value})
                task['pending'], task['error'], task['attempts'], task['retry_at'] = None, '', 0, 0
                task['state'] = 'READY'
                if pending.get('complete_after'):
                    task['state'] = 'COMPLETED'
                    if isinstance(value, dict) and value.get('status') == 'collected':
                        task['answer'] = f"Copied {value['copied']} related files to {value['folder']}. Originals were preserved.\n{value['note']}\nDownload: {value['artifact']}"
                    elif isinstance(value, dict) and value.get('status') == 'no_matches':
                        task['answer'] = 'No related files were found. ' + value.get('note', '')
                    elif isinstance(value, dict) and value.get('artifact'):
                        task['answer'] = 'Completed successfully. Saved: ' + value['artifact']
                    elif pending['tool'] == 'gmail_send':
                        task['answer'] = f"Email sent to {pending['arguments']['to']}.\nSubject: {pending['arguments']['subject']}"
                    elif pending['tool'] == 'knowledge_index':
                        task['answer'] = f"Knowledge index updated: {value['extracted']} documents indexed, {value['cache_hits']} unchanged, {value['skipped_or_unreadable']} skipped." + (' Entry limit reached; index narrower folders to complete coverage.' if value.get('truncated') else '')
                    else:
                        task['answer'] = json.dumps(value, ensure_ascii=False)[:24000]
                self._save(task, 'checkpoint', pending['tool'] + ' completed; result committed')
            else:
                task['turns'] += 1
                task['error'], task['attempts'], task['retry_at'] = '', 0, 0
                if value['kind'] == 'finish':
                    task['answer'], task['state'] = value['summary'], 'COMPLETED'
                elif value['kind'] == 'ask':
                    task['question'], task['state'] = value['summary'], 'WAITING_INPUT'
                else:
                    spec = self.registry.tools[value['tool']]
                    permitted_output = task.get('auto_outputs', False) and (value['tool'] == 'document_export' or
                        (value['tool'] == 'files_collect' and 'files' in task['scopes']))
                    from services.mail_policy import authorize_send
                    permitted_email = authorize_send(task, value)
                    if permitted_email:
                        value['authorization'] = 'explicit_email_request'
                    permitted_output = permitted_output or permitted_email
                    task['pending'] = {**value, 'id': uuid.uuid4().hex, 'approved': permitted_output}
                    task['state'] = 'APPROVAL' if (spec['writes'] or spec['scope'] not in task['scopes']) and not permitted_output else 'READY'
                if task['turns'] >= task['max_turns'] and task['state'] not in TERMINAL:
                    task['state'], task['error'] = 'BLOCKED', 'Intent reached its 48-turn budget. Start a narrower follow-up goal.'
                self._save(task, 'decision', value['summary'])
            if task['cancel_requested'] and task['state'] != 'REVIEW':
                task['state'] = 'CANCELLED'
                self._save(task, 'cancelled', 'Cancelled at the next safe execution boundary; completed effects are recorded')
            elif task['pause_requested'] and task['state'] in ('READY', 'RECOVERY'):
                task['state'] = 'PAUSED'
                self._save(task, 'paused', 'Paused at checkpoint')
            self.cv.notify_all()
        return True

    def control(self, ident, action, data=None):
        data = data or {}
        with self.cv:
            if ident not in self.tasks:
                raise ValueError('Intent not found')
            task = self.tasks[ident]
            state = task['state']
            if action == 'approve' and state == 'APPROVAL':
                if data.get('action_id') != task['pending']['id']:
                    raise ValueError('Approval is stale; refresh the intent')
                task['pending']['approved'] = True
                task['state'] = 'READY'
            elif action == 'pin':
                task['pinned'] = bool(data.get('pinned'))
            elif action == 'priority':
                if data.get('priority') not in ('LOW', 'NORMAL', 'HIGH'):
                    raise ValueError('Choose a valid priority')
                task['priority'] = data['priority']
            elif action == 'deny' and state == 'APPROVAL':
                if data.get('action_id') != task['pending']['id']:
                    raise ValueError('Approval is stale; refresh the intent')
                task['history'].append({'action': task['pending'], 'observation': 'USER DENIED this action. Do not repeat it.'})
                task['pending'], task['state'] = None, 'READY'
            elif action == 'reply' and state == 'WAITING_INPUT':
                reply = data.get('text', '')
                if not isinstance(reply, str) or not reply.strip() or len(reply) > 12000:
                    raise ValueError('Enter a reply within 12000 characters')
                task['history'].append({'question': task['question'], 'user_reply': reply})
                task['question'], task['state'] = '', 'READY'
            elif action == 'pause' and state in ('RUNNING', 'READY', 'RECOVERY'):
                task['pause_requested'] = True
                task['state'] = 'PAUSING' if state == 'RUNNING' else 'PAUSED'
            elif action == 'cancel' and state not in TERMINAL and state not in ('REVIEW', 'CANCELLING'):
                task['cancel_requested'] = True
                task['state'] = 'CANCELLING' if state in ('RUNNING', 'PAUSING') else 'CANCELLED'
            elif action == 'resume' and state in ('PAUSED', 'BLOCKED'):
                if task['turns'] >= task['max_turns']:
                    raise ValueError('Turn budget exhausted; start a narrower goal')
                if state == 'BLOCKED' and not task.get('pending') and task['history'] and isinstance(task['history'][-1].get('observation'), dict) and task['history'][-1]['observation'].get('status') == 'rejected':
                    task['history'].append({'user_control': 'resume', 'after_rejected_request': True})
                task['state'], task['pause_requested'], task['attempts'], task['retry_at'] = 'READY', False, 0, 0
            elif action == 'skip' and state in ('BLOCKED', 'REVIEW'):
                task['history'].append({'action': task['pending'], 'observation': 'User skipped this action; its result is not confirmed. ' + task['error']})
                task['pending'], task['state'], task['attempts'], task['retry_at'] = None, 'READY', 0, 0
                task['cancel_requested'], task['pause_requested'] = False, False
            elif action == 'retry' and state == 'REVIEW':
                if data.get('action_id') != task['pending']['id'] or data.get('acknowledge_duplicate_risk') is not True:
                    raise ValueError('Review the possible side effect and acknowledge duplicate risk first')
                task['state'], task['attempts'], task['retry_at'] = 'READY', 0, 0
                task['cancel_requested'], task['pause_requested'] = False, False
            else:
                raise ValueError(f'Cannot {action} an intent in {state}')
            task['queued_at'] = time.time()
            self._save(task, 'user', action)
            return copy.deepcopy(task)

    def snapshot(self):
        with self.cv:
            tasks = []
            for t in sorted(self.tasks.values(), key=lambda t: t['created_at'], reverse=True):
                item = {k: copy.deepcopy(v) for k, v in t.items() if k != 'history'}
                # Keep event streams responsive for large collections; the complete
                # manifest remains on disk and in the durable task checkpoint.
                for step in item['steps']:
                    result = step.get('result')
                    if isinstance(result, dict):
                        for key in ('files', 'matches'):
                            if isinstance(result.get(key), list) and len(result[key]) > 50:
                                result[key + '_total'] = len(result[key])
                                result[key] = result[key][:50]
                item['deadline_missed'] = bool(t['deadline'] and (t['updated_at'] if t['state'] in TERMINAL else time.time()) > t['deadline'])
                from services.contracts import contract_status
                item['contract'] = contract_status(t)
                item['waiting_for'] = [i for i in t.get('depends_on', []) if self.tasks.get(i, {}).get('state') != 'COMPLETED']
                tasks.append(item)
            events = [{'seq': r[0], 'intent_id': r[1], 'timestamp': r[2], 'kind': r[3], 'message': r[4]}
                      for r in self.db.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 150')]
            return {'revision': self.revision, 'intents': tasks, 'events': events,
                    'scheduler': {'policy': self.policy, 'reason': self.reason, 'mode': self.config.scheduling, 'quantum': 'one decision or capability call', 'preemption': 'cooperative call boundaries'},
                    'resources': {'workers': self.config.execution['workers'], 'active': len(self.locks), 'locks': dict(self.locks), 'memory_throttled': self.config.execution['adaptive'] and self._host_sample[1] >= 90},
                    'config': self.config.public(), 'google': self.google.status(),
                    'capabilities': self.registry.catalog()}

    def start(self):
        def worker():
            while not self.stopping:
                if not self.tick():
                    with self.cv:
                        self.cv.wait(timeout=0.5)
        for index in range(8):
            thread = threading.Thread(target=worker, name=f'intent-worker-{index}', daemon=True)
            self.threads.append(thread)
            thread.start()

    def close(self):
        with self.cv:
            self.stopping = True
            self.cv.notify_all()
        for thread in self.threads:
            thread.join(timeout=1)
        if any(thread.is_alive() for thread in self.threads):
            # In-flight calls finish or the process exits. Keep DB/lease open until then.
            return
        self.db.close()
        self.lease.close()
