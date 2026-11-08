"""The CI gate: compare a run with a stored baseline and fail on regressions, not on < 100%.

Rules, in order:
- An eval that didn't run fails the build. Invalid runs, and judge checks that couldn't be graded,
  are regressions: a gate that goes green when nothing was graded is worse than no gate.
- An overall or unit score has more failures than the baseline rate predicts, by more than `allow`.
  The allowance is a count of failures, not a percentage: with 16 router tickets one flip is 6%,
  with 27 smoke checks one invented fact is 4%, and a percentage tolerance treats those differently.
- A check that never failed in the baseline fails now. Averages dilute; a check that always held
  and now doesn't is the regression. Build the PR baseline from the 3-run nightly results, so
  "never failed" means it held in all 3 runs, not in one lucky sample.
- Before blocking on a never-failed check, rerun only the failing (case, model) once. Block only
  if it fails both times. One flaky failure in a sampled system is not a regression.
"""

import json
from pathlib import Path

from evals.core import load_cases, summarize, uncached_checks


def make_baseline(results, tags=None):
    """Pass rates per model, check and unit component. With `tags`, only those cases count
    (the PR baseline is the nightly run restricted to the smoke cases)."""
    if tags:
        keep = {c["id"] for c in load_cases(tags=tags)}
        results = {**results, "rows": [r for r in results["rows"] if r["case"] in keep]}
    s = summarize(results)
    return {
        "models": results["models"],
        "runs": results.get("runs"),
        "by_model": {m: x["rate"] for m, x in s["by_model"].items()},
        "by_check": {c: {m: x["rate"] for m, x in per.items()} for c, per in s["by_check"].items()},
        "unit": {c: {m: x["rate"] for m, x in per.items()} for c, per in s["unit"].items()},
    }


def _fmt(rate):
    return "-" if rate is None else f"{rate:.0%}"


def compare(results, baseline, allow=1, reruns=None):
    """Returns (regressions, markdown). Each regression is a dict with a `label`, and for a
    never-failed check also `check`, `model` and the failing `cases`.
    `reruns` maps (check, model) -> True if it failed again on rerun, False if it passed."""
    s = summarize(results)
    regressions, lines, notes = [], [], []
    reruns = reruns or {}

    # 1. An eval that didn't run must fail the build.
    rows = results["rows"]
    invalid = [r for r in rows if r["status"] != "valid"]
    if invalid:
        first = next((r["error"] for r in invalid if r.get("error")), "empty reply")
        regressions.append({"label": f"{len(invalid)} of {len(rows)} runs invalid"})
        notes.append(f"**{len(invalid)} of {len(rows)} runs invalid**, so their checks weren't graded. First error: `{first}`")
    uncached = uncached_checks(results)
    if uncached:
        regressions.append({"label": f"not graded: {', '.join(uncached)}"})
        notes.append(f"**Not graded (no cached verdict, no API key):** {', '.join(uncached)}. "
                     "Add `ANTHROPIC_API_KEY` as a repository secret.")

    def row(label, before, now, gate, check=None, model=None):
        rate = now["rate"] if now else None
        if before is None:  # new check or model: nothing to compare against yet
            lines.append(f"| {label} | - | {_fmt(rate)} | new | |")
            return
        if rate is None:
            regressions.append({"label": f"{label}: not graded"})
            lines.append(f"| {label} | {_fmt(before)} | - | not graded | ❌ |")
            return
        n, fails = now["pass"] + now["fail"], now["fail"]
        expected = round((1 - before) * n, 1)
        if gate == "count":
            bad = fails - expected > allow
            delta = f"{fails} fail vs ~{expected:g} expected"
            mark = "❌" if bad else ""
        else:  # never failed in the baseline
            bad = before == 1.0 and fails > 0
            delta = f"{fails} fail" if fails else "+0"
            mark = "❌" if bad else ""
            if bad and (check, model) in reruns:
                if reruns[(check, model)]:
                    mark, delta = "❌", delta + ", failed again on rerun"
                else:
                    bad, mark, delta = False, "⚠️", delta + ", passed on rerun (flaky, not blocking)"
        if bad:
            failing = sorted({r["case"] for r in rows if r["model"] == model
                              for v in r["verdicts"] if v["check"] == check and v["verdict"] == "FAIL"}) if check else []
            regressions.append({"label": label, "check": check, "model": model, "cases": failing})
        lines.append(f"| {label} | {_fmt(before)} | {_fmt(rate)} | {delta} | {mark} |")

    for m in results["models"]:
        row(f"**{m}** overall", baseline["by_model"].get(m), s["by_model"].get(m), "count")
    for comp, per in s["unit"].items():
        for m, now in per.items():
            row(f"unit/{comp} ({m.split('/')[-1]})", baseline["unit"].get(comp, {}).get(m), now, "count")
    for check, per in s["by_check"].items():
        for m, now in per.items():
            row(f"{check} ({m.split('/')[-1]})", baseline["by_check"].get(check, {}).get(m), now, "never-failed",
                check=check, model=m)

    failed = [(r["case"], r["model"], v) for r in rows for v in r["verdicts"] if v["verdict"] == "FAIL"]
    md = ["## Evals", "",
          f"**{'❌ Regression' if regressions else '✅ No regression'}** against the baseline "
          f"(allowing {allow} extra failure{'s' if allow != 1 else ''} per score). "
          "The score shows where to look; open the transcript to decide.", ""]
    md += [f"- {n}" for n in notes] + ([""] if notes else [])
    md += ["| | baseline | this PR | Δ | |", "|---|---|---|---|---|", *lines, ""]
    if failed:
        md += ["<details><summary>Failed checks with evidence</summary>", ""]
        md += [f"- `{v['check']}` on `{case}` ({m.split('/')[-1]}): {v['evidence']}" for case, m, v in failed[:25]]
        md += ["", "</details>"]
    return regressions, "\n".join(md)


def skipped_report(message):
    return "\n".join(["## Evals", "", "**❌ Skipped: nothing was graded.**", "", message, "",
                      "An eval that didn't run fails the build. Add `ANTHROPIC_API_KEY` as a repository secret "
                      "(Settings → Secrets and variables → Actions), or commit the cache/ entries from a local run."])


def save_baseline(results, path, tags=None):
    Path(path).write_text(json.dumps(make_baseline(results, tags), indent=1), encoding="utf-8")
