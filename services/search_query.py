"""Small deterministic parser for file-search topics and modification dates."""
import re
from datetime import datetime, timedelta

DATE = r'(?:\d{4}-\d{2}-\d{2}|[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:,)?\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})'


def timestamp(value):
    value = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', value.strip(), flags=re.I).replace(',', '')
    for fmt in ('%Y-%m-%d', '%B %d %Y', '%b %d %Y', '%d %B %Y', '%d %b %Y'):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Use a valid date such as 2026-09-01 or September 1 2026') from None


def parse_query(query):
    if not isinstance(query, str) or not query.strip():
        raise ValueError('Provide a topic or meaningful search terms')
    filters = {}
    def date_clause(match):
        relation, value = match.group(1).lower(), match.group(2)
        date = timestamp(value)
        # "After September 1" excludes that calendar day; "since" includes it.
        if relation == 'after':
            date += timedelta(days=1)
        key = 'modified_before' if relation == 'before' else 'modified_after'
        if key in filters:
            raise ValueError('Use one lower and one upper date boundary')
        filters[key] = date.isoformat()
        return ' '
    query = re.sub(r'\b(?:which\s+were\s+|that\s+were\s+)?(?:(?:saved|modified|updated|created)\s+)?(after|since|before)\s+(' + DATE + r')\b', date_clause, query, flags=re.I)
    if re.search(r'\b(after|before|since)\b', query, re.I):
        raise ValueError('Use an explicit date, for example: AWS files saved after September 1 2026')
    return query.strip(), filters


def search_spec(args):
    query, filters = parse_query(args['query'])
    filters.update({k: v for k, v in args.items() if k in ('modified_after', 'modified_before')})
    bounds = {k: timestamp(v).timestamp() for k, v in filters.items()}
    if bounds.get('modified_after', float('-inf')) >= bounds.get('modified_before', float('inf')):
        raise ValueError('The start date must be before the end date')
    return query, filters, bounds


def goal_date_filters(goal):
    """Preserve explicit file-date clauses independently of model arguments."""
    found = re.search(r'\b(?:files?|documents?)\b\s+(?:(?:which|that)\s+(?:were\s+)?)?(?:(?:saved|modified|updated)\s+)?(?:after|since|before)\s+' + DATE, goal, re.I)
    if not found:
        return {}
    return parse_query(found.group(0))[1]
