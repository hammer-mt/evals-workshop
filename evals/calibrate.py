"""Audit the auditor: compare the judge's verdicts with your own blind labels.

Labels come from the viewer's label mode (labels/*.jsonl). About a third of them are held
out by hash, so you can tune check wording on the rest and measure honestly on the holdout.
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from evals.cache import CacheMiss
from evals.core import load_cases
from evals.judge import judge


def load_labels(paths):
    labels = {}
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                labels[(row["run_key"], row["check"])] = row  # later files win
    return labels


def is_holdout(run_key, check):
    return int(hashlib.sha256(f"{run_key}:{check}".encode()).hexdigest(), 16) % 3 == 0


def calibrate(results, labels, repeat=0, judge_model=None):
    cases = {c["id"]: c for c in load_cases()}
    by_check = defaultdict(lambda: {"dev": [], "holdout": []})
    disagreements = []
    flips = defaultdict(lambda: [0, 0])  # check -> [flipped, judged]

    for row in results["rows"]:
        for v in row["verdicts"]:
            if v["kind"] != "judge" or v["verdict"] == "NOT_RUN" or (row["key"], v["check"]) not in labels:
                continue
            human = labels[(row["key"], v["check"])]["label"]
            split = "holdout" if is_holdout(row["key"], v["check"]) else "dev"
            by_check[v["check"]][split].append((v["verdict"], human))
            if v["verdict"] != human:
                disagreements.append({"case": row["case"], "model": row["model"], "check": v["check"],
                                      "judge": v["verdict"], "human": human, "split": split,
                                      "evidence": v["evidence"], "note": labels[(row["key"], v["check"])].get("note", "")})
            if repeat:
                case = cases[row["case"]]
                check = next(c for c in case.get("checks", []) + _suite_checks(results) if c["id"] == v["check"])
                for r in range(1, repeat + 1):
                    try:
                        again = judge(check, case, row["transcript"], judge_model or results["judge"], repeat=r)
                    except CacheMiss:
                        continue  # offline and not cached: report agreement without the flip rate
                    flips[v["check"]][0] += again["verdict"] != v["verdict"]
                    flips[v["check"]][1] += 1

    report = {}
    for check, splits in sorted(by_check.items()):
        report[check] = {}
        for split, pairs in splits.items():
            n = len(pairs)
            report[check][split] = {
                "n": n,
                "agreement": round(sum(j == h for j, h in pairs) / n, 2) if n else None,
                "false_accusations": sum(j == "FAIL" and h == "PASS" for j, h in pairs),
                "misses": sum(j == "PASS" and h == "FAIL" for j, h in pairs),
            }
        if check in flips:
            f, n = flips[check]
            report[check]["flip_rate"] = round(f / n, 2)
    return report, disagreements


def _suite_checks(results):
    from evals.core import load_checks
    return load_checks(results["checks_file"])


def print_report(report, disagreements):
    print("\nJudge vs your labels. Target: ~90% agreement on the holdout.\n")
    print(f"{'check':34}{'dev agree':>11}{'holdout':>10}{'n':>5}{'false acc.':>12}{'misses':>8}{'flips':>7}")
    for check, r in report.items():
        d, h = r["dev"], r["holdout"]
        fmt = lambda x: f"{x:.0%}" if x is not None else "-"
        fa = d["false_accusations"] + h["false_accusations"]
        mi = d["misses"] + h["misses"]
        flips = f"{r['flip_rate']:.0%}" if "flip_rate" in r else "-"
        print(f"{check:34}{fmt(d['agreement']):>11}{fmt(h['agreement']):>10}{d['n'] + h['n']:>5}{fa:>12}{mi:>8}{flips:>7}")
    if disagreements:
        print("\nDisagreements: read these. Either the check is unclear, or your label is wrong.\n")
        for x in disagreements:
            print(f"- [{x['split']}] {x['check']} on {x['case']} ({x['model'].split('/')[-1]}): judge {x['judge']}, you {x['human']}")
            print(f"    judge's evidence: {x['evidence']}")
            if x["note"]:
                print(f"    your note: {x['note']}")
