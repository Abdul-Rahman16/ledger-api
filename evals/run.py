"""
Run the golden-question evals.

  python -m evals.run                         offline: recorded model replies, real database (CI mode)
  python -m evals.run --live                  real Groq/Gemini calls: measures routing accuracy
  python -m evals.run --live --report evals/reports/live.json
  python -m evals.run --only revenue_total top_2_regions
"""

import argparse

from evals.runner import run_eval, write_report


def print_report(report: dict) -> None:
    summary = report["summary"]
    print(
        f"Mode: {summary['mode']} - {summary['cases']} cases, {summary['passed']} passed, "
        f"{summary['failed']} failed ({summary['pass_rate'] * 100:.1f}%)"
    )
    for tag, counts in sorted(summary["by_tag"].items()):
        print(f"  {tag}: {counts['passed']}/{counts['total']}")

    failed = [case for case in report["cases"] if not case["passed"]]
    if failed:
        print("\nFailed cases:")
        for case in failed:
            print(f"  - {case['id']}")
            for failure in case["failures"]:
                print(f"      {failure}")

    if "routing" in summary:
        routing = summary["routing"]
        print("\nRouting accuracy (real model):")
        print(f"  status accuracy:  {routing['status_accuracy'] * 100:.1f}%")
        if routing["full_spec_match"] is not None:
            print(f"  full spec match:  {routing['full_spec_match'] * 100:.1f}% of {routing['spec_cases']} cases")
        for name, entry in sorted(routing["field_accuracy"].items()):
            print(f"    {name}: {entry['correct']}/{entry['total']} ({entry['accuracy'] * 100:.1f}%)")
        print(f"  average latency:  {summary['latency_ms_avg']:.0f} ms per question")
        print(f"  tokens used:      {summary['tokens_total']}")

    if report["invariant_problems"]:
        print("\nInvariant problems:")
        for problem in report["invariant_problems"]:
            print(f"  - {problem}")
    else:
        print("\nInvariants: OK (every logged query passed the SQL gate; the datasets table is intact)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the Ledger golden-question evals.")
    parser.add_argument("--live", action="store_true", help="use the real language models")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between live calls")
    parser.add_argument("--only", nargs="*", help="run only these case ids")
    parser.add_argument("--report", help="write the full JSON report to this path")
    args = parser.parse_args(argv)

    try:
        report = run_eval(
            mode="live" if args.live else "offline",
            delay=args.delay,
            only=set(args.only) if args.only else None,
        )
    except RuntimeError as exc:
        print(f"Cannot run: {exc}")
        return 2

    print_report(report)
    if args.report:
        write_report(report, args.report)
        print(f"\nReport written to {args.report}")

    if report["invariant_problems"]:
        return 1
    # Offline results are deterministic and must be perfect. Live accuracy is reported, not gated.
    if not args.live and report["summary"]["failed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())