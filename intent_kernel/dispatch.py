"""Shared strict-priority ordering; callers own runnable-state and resource checks."""
PRIORITY = {'HIGH': 0, 'NORMAL': 1, 'LOW': 2}


def strict_pick(ready, order):
    return min(ready, key=lambda p: (PRIORITY[p['priority']], order(p)), default=None)
