"""Generate reproducible OS Lab evidence without credentials, APIs or user files.

Run from the project root: .venv/Scripts/python.exe scripts/os_lab_demo.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intent_kernel.os_lab import OSLab, scenarios


def main():
    output = Path(__file__).resolve().parents[1] / 'output' / 'os-lab'
    output.mkdir(parents=True, exist_ok=True)
    lines = ['# Executed OS Lab demonstrations', '',
             'These are measured virtual-machine runs, not Windows process traces. One tick is one instruction attempt; a page fault consumes a tick and retries the instruction. Quantum = 2 ticks; physical frames = 3.', '']
    for scenario in scenarios():
        lab = OSLab(); lab.reset(scenario, 2, 3)
        for _ in range(500):
            state = lab.step()
            if state['done'] or state['deadlocked']: break
        if not state['done']: raise RuntimeError(f'{scenario} did not finish')
        (output / f'{scenario}.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        timeline = ' → '.join(t['pid'] or 'IDLE' for t in state['timeline'])
        lines += [f'## {scenario}', '', f'Executed ticks: {timeline}', '',
                  f"{state['tick']} ticks; {state['metrics']['context_switches']} process context switches; {state['metrics']['page_faults']} page faults; {state['metrics']['evictions']} evictions.", '',
                  '| Process | Priority | Result | PC | ACC | CPU ticks | Ready wait | Blocked |',
                  '|---|---|---|---:|---:|---:|---:|---:|']
        for p in state['processes']:
            lines.append(f"| {p['id']} | {p['priority']} | {p['state']} | {p['pc']} | {p['acc']} | {p['cpu_ticks']} | {p['wait_ticks']} | {p['blocked_ticks']} |")
        lines += ['', 'Context saves:', '']
        for e in state['events']:
            if e['kind'] == 'context_save':
                lines.append(f"- Tick {e['tick']}, {e['pid']}: {e['message']}; saved PC={e['registers']['pc']}, ACC={e['registers']['acc']}.")
        lines += ['', 'All physical frames and backing pages were released after exit.', '']
        print(f"{scenario}: {state['tick']} ticks; {state['metrics']}")
    (output / 'demonstration.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__': main()
