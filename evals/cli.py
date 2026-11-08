"""evals: the workshop's command line.

  evals check-setup                     can you run live, or only replay from cache?
  evals run [--models a,b] [--runs 3]   replay cases, grade them, write runs/<name>/ and its viewer
  evals view <run>                      rebuild a run's viewer
  evals calibrate <run> --labels f      judge vs your labels; --repeat 3 tests judge stability
  evals baseline <run>                  store a run as the CI baseline
  evals ci [--tier pr|nightly]          run a tier and fail on regressions against the baseline
  evals online <logs.jsonl>             grade logged production conversations (no replay)
  evals capture <logs.jsonl> --id X     turn a logged conversation into a regression case
"""

import argparse
import glob
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from evals import cache  # noqa: E402
from evals.core import (DEFAULT_JUDGE, DEFAULT_MODELS, ROOT, load_run, print_summary,  # noqa: E402
                        run_suite, run_unit, save)

TIERS = {
    # Every PR: unit evals + the smoke cases, one run each. Seconds and cents.
    "pr": {"tags": ["smoke"], "runs": 1},
    # Nightly: every case, three runs each.
    "nightly": {"tags": None, "runs": 3},
}


def cmd_check_setup(a):
    print(f"Python {sys.version.split()[0]}")
    import dspy
    print(f"dspy {dspy.__version__}")
    n = len(glob.glob(str(cache.CACHE_DIR / "*" / "*.json")))
    print(f"{n} cached results in cache/")
    if cache.offline():
        print("No API key found: running OFFLINE. Every step replays from cache/. "
              "Judge checks you write yourself show as 'not graded' until you add a key.")
    else:
        print(f"API key found: live runs enabled. Models: {', '.join(DEFAULT_MODELS)}. Judge: {DEFAULT_JUDGE}.")
    print("Setup OK.")


def run_and_report(models, runs, cases, tags, checks, judge, prompt, name, unit):
    results = run_suite(models, runs, cases, tags, checks, judge, prompt)
    if unit:
        results["unit"] = run_unit(models, runs)
    out = save(results, name)
    from evals.viewer import write_viewer
    html = write_viewer(results, out)
    print_summary(results)
    print(f"\nSaved {out.relative_to(ROOT)}/results.json\nViewer: {html}")
    return results


def cmd_run(a):
    run_and_report(a.models.split(","), a.runs, a.cases.split(",") if a.cases else None,
                   a.tags.split(",") if a.tags else None, a.checks, a.judge, a.prompt, a.name, a.unit)


def cmd_view(a):
    from evals.viewer import write_viewer
    results = load_run(a.run)
    print(write_viewer(results, ROOT / "runs" / Path(a.run).name))


def cmd_calibrate(a):
    from evals.calibrate import calibrate, load_labels, print_report
    paths = [p for pattern in a.labels for p in glob.glob(pattern)]
    if not paths:
        sys.exit(f"No label files match {a.labels}. Label in the viewer (Label mode), download labels.jsonl, and pass it here.")
    report, disagreements = calibrate(load_run(a.run), load_labels(paths), repeat=a.repeat)
    print_report(report, disagreements)


def cmd_baseline(a):
    from evals.ci import save_baseline
    save_baseline(load_run(a.run), a.out, a.tags.split(",") if a.tags else None)
    print(f"Wrote {a.out}")


def cmd_ci(a):
    import json
    from evals.ci import compare, skipped_report
    tier = TIERS[a.tier]
    report = Path(a.report)
    try:
        results = run_and_report(a.models.split(","), tier["runs"], None, tier["tags"], a.checks, a.judge, None,
                                 f"ci-{a.tier}", True)
    except cache.CacheMiss as e:
        report.write_text(skipped_report(str(e)), encoding="utf-8")
        sys.exit(f"{e}\nWrote {a.report}. An eval that didn't run fails the build.")
    baseline = json.loads(Path(a.baseline).read_text(encoding="utf-8"))
    regressions, md = compare(results, baseline, a.allow)

    # Rerun only what failed a never-failed check, once, at run index 1. Block only on 2 of 2.
    flagged = [r for r in regressions if r.get("check")]
    if flagged and a.rerun:
        reruns = {}
        print(f"\nRerunning {sum(len(r['cases']) for r in flagged)} failing (case, model) pair(s) once to confirm...")
        for r in flagged:
            again = []
            for case_id in r["cases"]:
                try:
                    out = run_suite([r["model"]], 1, [case_id], None, a.checks, a.judge, None, run_ids=[1])
                except cache.CacheMiss:
                    again.append(True)  # can't confirm offline: keep it blocking
                    continue
                again += [v["verdict"] == "FAIL" for row in out["rows"] for v in row["verdicts"] if v["check"] == r["check"]]
            reruns[(r["check"], r["model"])] = any(again)
        regressions, md = compare(results, baseline, a.allow, reruns)

    report.write_text(md, encoding="utf-8")
    print(f"\nWrote {a.report}")
    if regressions:
        print("Regressions: " + "; ".join(r["label"] for r in regressions))
        sys.exit(1)
    print("No regressions.")


def cmd_online(a):
    from evals.production import grade_logs, print_logs
    print_logs(grade_logs(a.logs, a.sample, a.checks, a.judge))


def cmd_capture(a):
    from evals.production import capture
    out = capture(a.logs, a.id)
    print(f"Wrote {out.relative_to(ROOT)}. Edit its TODO check, approve it (delete `status: candidate`), then rerun.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="evals", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--models", default=",".join(DEFAULT_MODELS))
        sp.add_argument("--judge", default=DEFAULT_JUDGE)
        sp.add_argument("--checks", help="suite checks file (default suites/support/checks.yaml)")

    sub.add_parser("check-setup").set_defaults(fn=cmd_check_setup)

    sp = sub.add_parser("run"); common(sp)
    sp.add_argument("--runs", type=int, default=1)
    sp.add_argument("--cases", help="comma-separated case ids")
    sp.add_argument("--tags", help="comma-separated tags, e.g. smoke")
    sp.add_argument("--prompt", help="alternative bot prompt file")
    sp.add_argument("--name", help="run name (default: timestamp)")
    sp.add_argument("--unit", action="store_true", help="also run the unit evals (router, injection detector)")
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("view"); sp.add_argument("run"); sp.set_defaults(fn=cmd_view)

    sp = sub.add_parser("calibrate"); sp.add_argument("run")
    sp.add_argument("--labels", nargs="+", default=["labels/*.jsonl"])
    sp.add_argument("--repeat", type=int, default=0, help="rerun the judge N more times on each labeled item")
    sp.set_defaults(fn=cmd_calibrate)

    sp = sub.add_parser("baseline"); sp.add_argument("run"); sp.add_argument("--out", default="baseline.json")
    sp.add_argument("--tags", help="only count these cases, e.g. smoke for the PR baseline")
    sp.set_defaults(fn=cmd_baseline)

    sp = sub.add_parser("ci"); common(sp)
    sp.add_argument("--tier", choices=TIERS, default="pr")
    sp.add_argument("--baseline", default="baseline.json")
    sp.add_argument("--allow", type=int, default=1, help="extra failures allowed per score before it counts as a regression")
    sp.add_argument("--no-rerun", dest="rerun", action="store_false", help="block on the first failure, no confirming rerun")
    sp.add_argument("--report", default="ci-report.md")
    sp.set_defaults(fn=cmd_ci)

    sp = sub.add_parser("online"); common(sp); sp.add_argument("logs")
    sp.add_argument("--sample", type=int, default=0)
    sp.set_defaults(fn=cmd_online)

    sp = sub.add_parser("capture"); sp.add_argument("logs"); sp.add_argument("--id")
    sp.set_defaults(fn=cmd_capture)

    a = p.parse_args(argv)
    os.chdir(ROOT)
    import litellm
    spent = []
    litellm.success_callback = [lambda kwargs, *_: spent.append(kwargs.get("response_cost") or 0)]
    try:
        a.fn(a)
    except cache.CacheMiss as e:
        sys.exit(str(e))
    finally:
        if spent:
            print(f"\n{len(spent)} model calls, ${sum(spent):.2f} (cached results cost nothing)")


if __name__ == "__main__":
    main()
