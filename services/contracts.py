"""Deterministic checks of observable output requirements, not LLM truth scoring."""
import re
from services.summary_policy import PlanCorrection, summary_requirements


def contract_status(task):
    # Prove contiguous coverage from checkpoint metadata, not the bounded LLM context.
    documents = {}
    for step in task.get('steps', []):
        result = step.get('result') or {}
        results = result.get('documents', []) if step.get('tool') == 'files_read_many' else [result] if step.get('tool') in ('files_read', 'files_ocr') else []
        for item in results:
            if item.get('content', '').strip():
                documents.setdefault(item['path'], []).append(item)
    read = set()
    for path, parts in documents.items():
        if any(p.get('ocr') or 'next_page' in p for p in parts):
            pages = {p.get('page', 1): p for p in parts if not p.get('truncated')}
            if pages and all(i in pages for i in range(1, max(p.get('pages', p.get('page', 1)) for p in parts) + 1)):
                read.add(path)
        else:
            offsets = {int(p.get('offset', 0)): p for p in parts}
            offset, visited = 0, set()
            while offset in offsets and offset not in visited:
                visited.add(offset)
                part = offsets[offset]
                if not part.get('truncated'):
                    read.add(path)
                    break
                if part.get('next_offset') is None:
                    break
                offset = int(part['next_offset'])
    required = [a for a in task.get('attachments', []) if a.get('role') == 'reference' or re.search(r'\b(?:all|every|attached|uploaded|these)\b', task.get('goal', ''), re.I)]
    requirements = summary_requirements(task)
    return {**requirements, 'required_attachments': len(required), 'read_attachments': sum(a['path'] in read for a in required),
            'unread_attachments': [a['name'] for a in required if a['path'] not in read],
            'citations_available': sum(len(s.get('result', {}).get('matches', [])) for s in task.get('steps', []) if s.get('tool') in ('knowledge_search', 'dataset_search'))}


def validate_completion(task, action):
    tool = action.get('tool')
    if action.get('kind') != 'finish' and tool not in ('gmail_send', 'document_export'):
        return
    args = action.get('arguments', {})
    text = action.get('summary', '') if action.get('kind') == 'finish' else args.get('body', args.get('content', ''))
    if action.get('kind') == 'finish':
        # A completion receipt can be brief when the full deliverable was committed.
        outputs = [s for s in task.get('steps', []) if s.get('tool') in ('document_export', 'gmail_send')]
        if outputs:
            output_args = outputs[-1].get('arguments', {})
            text = output_args.get('body', output_args.get('content', '')) or text
    status = contract_status(task)
    if status['unread_attachments']:
        raise PlanCorrection('Read the required source/reference attachments before completing: ' + ', '.join(status['unread_attachments']))
    if status['remaining_assessment_documents']:
        raise PlanCorrection('Read these assessments completely before completing: ' + '; '.join(status['remaining_assessment_documents']))
    if status['minimum_nonempty_lines'] and sum(bool(l.strip()) for l in text.splitlines()) < status['minimum_nonempty_lines']:
        raise PlanCorrection(f"Output needs {status['minimum_nonempty_lines']} nonempty lines. Expand it using the evidence.")
    available = {m['citation'] for s in task.get('steps', []) if s.get('tool') in ('knowledge_search', 'dataset_search') for m in s.get('result', {}).get('matches', [])}
    # Models sometimes group citations as [S-12345678, S-abcdef12].
    # Validate every marker in the group rather than rejecting valid groups or
    # overlooking an unknown marker next to a valid one.
    groups = re.findall(r'\[([^\]\n]*\bS-[^\]\n]*)\]', text)
    used = {'[' + marker + ']' for group in groups for marker in re.findall(r'\bS-[A-Za-z0-9_-]+', group)}
    if used - available:
        raise PlanCorrection('Use only citation markers returned by knowledge_search or dataset_search; some citations are unknown.')
    if available and not used:
        raise PlanCorrection('Cite retrieved evidence next to supported claims using these exact markers: ' + ', '.join(sorted(available)) + '. For kind=finish, put the complete cited answer in summary, with tool="" and arguments={}; do not put it in an extra answer or body field.')
