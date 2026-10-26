"""Check observable coverage and requested length before emailing assessments."""
import re
from pathlib import Path


class PlanCorrection(ValueError):
    """A local preflight rejection: no external action has been attempted."""
    retryable = True


def review_brief_requirements(task):
    texts = [task.get('goal', ''), *[e['user_reply'] for e in task.get('history', []) if isinstance(e.get('user_reply'), str)]]
    goal = '\n'.join(texts)
    active = bool(re.search(r'\bproject\s+review\b', goal, re.I) and re.search(r'\bsummar(?:y|i[sz]e)\b', goal, re.I)
                  and re.search(r'\b(?:e-?mail|mail)\b', goal, re.I)
                  and re.search(r'\b(?:repo|repository|read|search|document|description)\b', goal, re.I))
    if not active:
        return {'project_review_brief': False, 'minimum_email_words': 0, 'unfinished_summary_sources': []}
    documents = {}
    for step in task.get('steps', []):
        result = step.get('result') or {}
        results = result.get('documents', []) if step.get('tool') == 'files_read_many' else [result] if step.get('tool') == 'files_read' else []
        for item in results:
            if item.get('content') and item.get('path'):
                documents.setdefault(item['path'], {})[int(item.get('offset', 0))] = item
    pending, source_length = [], 0
    for path, parts in documents.items():
        source_length += sum(len(part['content']) for part in parts.values())
        offset, seen = 0, set()
        while offset in parts and offset not in seen:
            seen.add(offset)
            part = parts[offset]
            if not part.get('truncated') or part.get('next_offset') is None:
                break
            cursor = str(part['next_offset'])
            if not re.fullmatch(r'\d{1,7}', cursor) or int(cursor) <= offset:
                break
            offset = int(cursor)
            if offset not in parts:
                pending.append({'path': path, 'next_offset': cursor})
                break
    # This is a minimum-detail guard, not a claim to score semantic completeness.
    # Explicit brevity/word counts win; short sources must not be padded.
    minimum = 220 if source_length >= 2000 else 0
    for text in reversed(texts):
        if re.search(r'\b(?:brief|short|concise|\d+\s+words|one[- ]paragraph)\b', text, re.I):
            minimum = 0
            break
        if re.search(r'\b(?:detailed|comprehensive|in[- ]depth)\b', text, re.I):
            break
    return {'project_review_brief': True, 'minimum_email_words': minimum, 'unfinished_summary_sources': pending}


def summary_requirements(task):
    goal = '\n'.join([task.get('goal', ''), *[e['user_reply'] for e in task.get('history', []) if isinstance(e.get('user_reply'), str)]])
    minimum = 0
    for match in re.finditer(r'\b(more\s+(?:than|that)|over|at\s+least)\s+(\d{1,4})\s+lines\b', goal, re.I):
        minimum = max(minimum, int(match[2]) + (0 if match[1].lower() == 'at least' else 1))
    remaining, available = [], []
    if re.search(r'\ball\s+(?:the\s+)?assessments\b', goal, re.I):
        complete = set()
        pages = {}
        steps = []
        for step in task.get('steps', []):
            if step.get('tool') == 'files_read_many':
                steps.extend({'tool': 'files_read', 'result': r} for r in (step.get('result') or {}).get('documents', []))
            else:
                steps.append(step)
        for step in steps:
            result = step.get('result') or {}
            if step.get('tool') in ('files_read', 'files_ocr') and result.get('content', '').strip():
                pages.setdefault(str(result.get('path', '')).casefold(), {})[int(result.get('offset', 0))] = result
        for path, chunks in pages.items():
            offset, visited = 0, set()
            while offset in chunks and offset not in visited:
                visited.add(offset)
                chunk = chunks[offset]
                if not chunk.get('truncated'):
                    complete.add(path)
                    break
                if chunk.get('next_offset') is None:
                    break
                offset = int(chunk['next_offset'])
        groups = {}
        for step in task.get('steps', []):
            if step.get('tool') != 'files_list':
                continue
            for entry in (step.get('result') or {}).get('entries', []):
                path = entry.get('path', '')
                if entry.get('directory') or Path(path).suffix.lower() not in ('.docx', '.pdf', '.txt', '.md'):
                    continue
                name = re.search(r'\bass(?:essment|ignment)?\s*[-_ ]*\s*(\d+)\b', entry.get('name', ''), re.I)
                if name:
                    groups.setdefault((str(Path(path).parent).casefold(), int(name[1])), []).append(path)
        for (_, number), paths in sorted(groups.items()):
            available.append(number)
            if not any(p.casefold() in complete for p in paths):
                remaining.append(sorted(paths, key=lambda p: (Path(p).suffix.lower() != '.docx', p))[0])
    return {'minimum_nonempty_lines': minimum, 'available_assessments': sorted(set(available)),
            'remaining_assessment_documents': remaining, **review_brief_requirements(task)}


def validate_summary_send(task, action):
    if action.get('tool') not in ('gmail_send', 'gmail_draft'):
        return
    requirements = summary_requirements(task)
    if requirements['unfinished_summary_sources']:
        raise PlanCorrection('Finish reading the project source before drafting its review summary. Use files_read with these next offsets: '
                             + '; '.join(f"{s['path']} offset={s['next_offset']}" for s in requirements['unfinished_summary_sources']))
    if requirements['remaining_assessment_documents']:
        raise PlanCorrection('Read these assessments completely before sending: ' + '; '.join(requirements['remaining_assessment_documents']))
    minimum = requirements['minimum_nonempty_lines']
    actual = sum(bool(line.strip()) for line in action.get('arguments', {}).get('body', '').splitlines())
    if actual < minimum:
        raise PlanCorrection(f'The requested summary needs at least {minimum} nonempty lines; the draft has {actual}. Expand the evidence-based summary and propose gmail_send again. No email was sent.')
    words = len(action.get('arguments', {}).get('body', '').split())
    if words < requirements['minimum_email_words']:
        raise PlanCorrection(f"This source-based project-review email needs at least {requirements['minimum_email_words']} words; the draft has {words}. Include useful source-supported detail on purpose, architecture/workflow, implemented features, OS concepts and limitations, then the verified event, Meet link and route. Do not invent filler. No email was sent.")
