"""Check observable coverage and requested length before emailing assessments."""
import re
from pathlib import Path


class PlanCorrection(ValueError):
    """A local preflight rejection: no external action has been attempted."""
    retryable = True


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
            'remaining_assessment_documents': remaining}


def validate_summary_send(task, action):
    if action.get('tool') != 'gmail_send':
        return
    requirements = summary_requirements(task)
    if requirements['remaining_assessment_documents']:
        raise PlanCorrection('Read these assessments completely before sending: ' + '; '.join(requirements['remaining_assessment_documents']))
    minimum = requirements['minimum_nonempty_lines']
    actual = sum(bool(line.strip()) for line in action.get('arguments', {}).get('body', '').splitlines())
    if actual < minimum:
        raise PlanCorrection(f'The requested summary needs at least {minimum} nonempty lines; the draft has {actual}. Expand the evidence-based summary and propose gmail_send again. No email was sent.')
