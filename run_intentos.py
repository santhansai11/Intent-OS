"""IntentOS command line interface.

Examples:
    python run_intentos.py "Prepare everything for my 4 PM meeting."
    python run_intentos.py "Write a brief summary of quantum computing"
    python run_intentos.py --demo --scheduler deadline
    python run_intentos.py --compare
    python run_intentos.py --app                 # full application (UI + API)
"""
from __future__ import annotations

import argparse
import sys

from intent_kernel.intent import COMPLETED, FAILED
from intent_kernel.kernel import IntentKernel
from intent_kernel.scheduler import SCHEDULERS
from intent_kernel.simulation import DEFAULT_WORKLOAD, compare_strategies

DEFAULT_STRATEGY = "auto"


def _configure_stdout() -> None:
    """Make console output UTF-8 safe.

    Generated content (LLM briefs, article extracts) can contain characters
    such as non-breaking hyphens that the Windows cp1252 console cannot
    encode; without this the CLI crashes while printing results.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - old/odd streams
            pass


# ---------------------------------------------------------------------------
def _print_summary(kernel: IntentKernel, intent) -> None:
    print()
    print(intent.describe())
    if intent.state == COMPLETED:
        print("\n  Result for the user:")
        for line in kernel.result_summary(intent):
            print(f"    - {line}")
        artifacts = kernel.artifacts(intent)
        if artifacts:
            print("\n  Files written:")
            for item in artifacts:
                marker = "new " if item["created"] else "upd "
                print(f"    [{marker}] {item['display_path']} "
                      f"({item['bytes']} bytes, {item['format']})")
            print("    Open them from the Artifacts panel of the web UI, "
                  "or run: python run_intentos.py --app")
    elif intent.state == FAILED:
        print(f"\n  Failed: {intent.last_error}")

    print()


def cmd_run(kernel: IntentKernel, text: str) -> None:
    intent = kernel.submit_text(text)
    kernel.run_all()
    _print_summary(kernel, intent)


def cmd_demo(kernel: IntentKernel) -> None:
    demos = [
        "Prepare everything for my 4 PM meeting.",
        "Submit my assignment to the professor before midnight",
        "Download the lecture videos",
        "Remind me to call mom at 18:30",
        "Show my schedule for today",
    ]
    print("Submitting demo intents:")
    for text in demos:
        intent = kernel.submit_text(text)
        print(f"  {intent.id}  [{intent.priority:6s}]  {intent.goal}")
    print(f"\nScheduler strategy: {kernel.strategy}\n")
    kernel.run_all()
    for intent in sorted(kernel.intents.values(), key=lambda i: i.id):
        _print_summary(kernel, intent)
    print("Kernel metrics:", kernel.metrics())


def cmd_compare() -> None:
    print("Synthetic workload:")
    for t in DEFAULT_WORKLOAD:
        dl = f"deadline={t.deadline}" if t.deadline is not None else "no deadline"
        print(f"  {t.name:20s} priority={t.priority:6s} cost={t.cost:2d} {dl}")
    print("\nStrategy comparison (same workload, one simulated resource):\n")
    header = f"  {'strategy':12s} {'avg wait':>9s} {'avg turn':>9s} {'missed':>7s}  completion order"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in compare_strategies():
        order = " -> ".join(row["completion_order"])
        print(
            f"  {row['strategy']:12s} {row['avg_waiting']:9.2f} "
            f"{row['avg_turnaround']:9.2f} {row['deadline_misses']:7d}  {order}"
        )


def cmd_server(port: int) -> None:
    from api.server import serve
    serve(port)


def cmd_app(port: int, open_browser: bool = True) -> None:
    """Start the complete application: kernel + API + built-in web UI."""
    from api.server import serve
    serve(port, open_browser=open_browser)


def main(argv=None) -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description="IntentOS prototype")
    parser.add_argument("text", nargs="*", help="natural language goal")
    parser.add_argument("-s", "--scheduler", default=DEFAULT_STRATEGY,
                        choices=sorted(SCHEDULERS),
                        help="scheduling policy; 'auto' (default) chooses one per workload")
    parser.add_argument("--demo", action="store_true", help="run the multi-intent demo")
    parser.add_argument("--compare", action="store_true", help="compare scheduling strategies")
    parser.add_argument("--app", action="store_true",
                        help="start the full application (API + web UI in one command)")
    parser.add_argument("--server", action="store_true", help="start the REST API server only")
    parser.add_argument("--no-browser", action="store_true",
                        help="with --app, do not auto-open the browser")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--latency", type=float, default=0.0, help="simulated service latency (s)")
    args = parser.parse_args(argv)

    if args.compare:
        cmd_compare()
        return 0
    if args.app or args.server:
        cmd_app(args.port, open_browser=args.app and not args.no_browser)
        return 0

    kernel = IntentKernel(strategy=args.scheduler, latency=args.latency)
    if args.demo:
        cmd_demo(kernel)
    elif args.text:
        cmd_run(kernel, " ".join(args.text))
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
