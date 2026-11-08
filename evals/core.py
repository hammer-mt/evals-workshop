"""Load cases and checks, replay conversations, grade them, and summarize."""

import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import dspy
import yaml

from bot.agent import PROMPT_PATH, SupportBot, injection_detector, make_lm, router
from evals.cache import CacheMiss, cached, key
from evals.code_checks import CHECKS
from evals.judge import judge

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "suites" / "support"
RUNS = ROOT / "runs"

BOT_VERSION = "2"  # bump when bot/agent.py changes in a way that should invalidate cached runs
# `or` rather than a getenv default, so an empty variable (an unset GitHub repo var) still gets the default
DEFAULT_MODELS = (os.getenv("EVALS_MODELS") or "anthropic/claude-haiku-5-5,anthropic/claude-sonnet-5-5").split(",")
DEFAULT_JUDGE = os.getenv("EVALS_JUDGE") or "anthropic/claude-opus-5-5"
NEEDS_KEY = "needs an API key"  # evidence prefix for a judge verdict that is not in cache/ and could not be computed


# --- Loading -----------------------------------------------------------------

def load_cases(ids=None, tags=None, suite=SUITE):
    cases = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted((suite / "cases").glob("*.yaml"))]
    if ids:
        cases = [c for c in cases if c["id"] in ids]
    if tags:
        cases = [c for c in cases if set(tags) & set(c.get("tags", []))]
    return cases


def load_checks(path=None):
    path = Path(path) if path else SUITE / "checks.yaml"
    checks = yaml.safe_load(path.read_text(encoding="utf-8"))["checks"]
    for c in checks:
        c["scope"] = "suite"
    return checks


def checks_for(case, suite_checks):
    """Suite checks plus the case's own. Candidate checks (drafted, not yet approved) are skipped."""
    own = [{**c, "scope": "case"} for c in case.get("checks", [])]
    return [c for c in suite_checks + own if c.get("status") != "candidate"]


# --- Replay ------------------------------------------------------------------

def run_case(case, model, run, prompt):
    """Replay one scripted conversation. Cached on everything that changes the bot's behavior."""
    replay_inputs = {k: case.get(k) for k in ("turns", "user_id", "today", "store_overrides")}

    def compute():
        with dspy.context(lm=make_lm(model)):
            bot = SupportBot(case.get("store_overrides"), prompt=prompt)
            return {"transcript": bot.converse(case["turns"], case["user_id"], case["today"])}

    k = key("run", BOT_VERSION, replay_inputs, model, prompt, run)
    try:
        out = cached("runs", k, compute)
        status = "valid" if out["transcript"] and all(t["reply"].strip() for t in out["transcript"]) else "invalid"
        return {"key": k, "status": status, "error": None, **out}
    except CacheMiss:
        raise
    except Exception as e:  # a crashed run is a fact about the run, not a FAIL for the bot
        return {"key": k, "status": "invalid", "error": f"{type(e).__name__}: {e}", "transcript": []}


def grade(case, result, checks, judge_model, repeat=0):
    verdicts = []
    for check in checks:
        row = {"check": check["id"], "kind": check["kind"], "scope": check["scope"]}
        if result["status"] != "valid":
            verdicts.append({**row, "verdict": "NOT_RUN", "evidence": result["error"] or "invalid run"})
            continue
        if check["kind"] == "code":
            verdict, evidence = CHECKS[check["fn"]](result["transcript"], case, **check.get("args", {}))
            verdicts.append({**row, "verdict": verdict, "evidence": evidence})
        else:
            try:
                out = judge(check, case, result["transcript"], judge_model, repeat=repeat)
            except CacheMiss:
                # Offline and this exact check text was never judged: say so and keep going, so the
                # code checks still grade and the viewer still opens. `evals ci` turns these into a failure.
                out = {"verdict": "NOT_RUN", "evidence": f"{NEEDS_KEY} (judge check {check['id']} isn't in cache/)",
                       "uncached": True}
            verdicts.append({**row, **out})
    return verdicts


def run_suite(models, runs=1, case_ids=None, tags=None, checks_path=None, judge_model=DEFAULT_JUDGE,
              prompt_path=None, workers=8, run_ids=None):
    """`run_ids` picks which run indices to replay (default 0..runs-1). CI reruns a failure at index 1."""
    prompt = Path(prompt_path).read_text(encoding="utf-8") if prompt_path else PROMPT_PATH.read_text(encoding="utf-8")
    suite_checks = load_checks(checks_path)
    cases = load_cases(case_ids, tags)
    jobs = [(c, m, r) for c in cases for m in models for r in (run_ids or range(runs))]

    def job(args):
        case, model, run = args
        result = run_case(case, model, run, prompt)
        return {
            "case": case["id"], "family": case.get("family"), "model": model, "run": run,
            **result, "verdicts": grade(case, result, checks_for(case, suite_checks), judge_model),
        }

    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(job, jobs))
    return {
        "created": datetime.now().isoformat(timespec="seconds"),
        "models": models, "runs": runs, "judge": judge_model,
        "checks_file": str(checks_path or SUITE.relative_to(ROOT) / "checks.yaml"),
        "prompt_key": key(prompt),
        "rows": rows,
    }


# --- Unit evals: components with a right answer --------------------------------

def run_unit(models, runs=1, workers=8):
    unit = ROOT / "suites" / "unit"
    items = (
        [("router", r) for r in csv.DictReader((unit / "router.csv").open(encoding="utf-8", newline=""))]
        + [("injection", r) for r in csv.DictReader((unit / "injection.csv").open(encoding="utf-8", newline=""))]
    )

    def job(args):
        (component, item), model, run = args
        if component == "router":
            def compute():
                with dspy.context(lm=make_lm(model)):
                    return {"output": router(ticket_text=item["ticket_text"]).department}
            out = cached("unit", key("router", item["ticket_text"], model, run), compute)
            expected = item["department"]
        else:
            def compute():
                with dspy.context(lm=make_lm(model)):
                    return {"output": str(injection_detector(message=item["message"]).is_injection).lower()}
            out = cached("unit", key("injection", item["message"], model, run), compute)
            expected = item["is_injection"]
        return {"component": component, "input": next(iter(item.values())), "expected": expected,
                "output": out["output"], "model": model, "run": run,
                "verdict": "PASS" if out["output"] == expected else "FAIL"}

    jobs = [(i, m, r) for i in items for m in models for r in range(runs)]
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(job, jobs))


# --- Summaries ---------------------------------------------------------------

def score(verdicts):
    """Pass rate over PASS+FAIL. UNKNOWN and NOT_RUN are reported, never counted as either."""
    p = sum(v == "PASS" for v in verdicts)
    f = sum(v == "FAIL" for v in verdicts)
    return {"pass": p, "fail": f, "unknown": verdicts.count("UNKNOWN"), "not_run": verdicts.count("NOT_RUN"),
            "rate": round(p / (p + f), 3) if p + f else None}


def summarize(results):
    rows = results["rows"]
    out = {"by_model": {}, "by_check": {}, "unit": {}}
    for m in results["models"]:
        out["by_model"][m] = score([v["verdict"] for r in rows if r["model"] == m for v in r["verdicts"]])
    checks = sorted({v["check"] for r in rows for v in r["verdicts"]})
    for c in checks:
        out["by_check"][c] = {
            m: score([v["verdict"] for r in rows if r["model"] == m for v in r["verdicts"] if v["check"] == c])
            for m in results["models"]
        }
    for u in results.get("unit", []):
        out["unit"].setdefault(u["component"], {}).setdefault(u["model"], []).append(u["verdict"])
    out["unit"] = {c: {m: score(v) for m, v in ms.items()} for c, ms in out["unit"].items()}
    return out


def print_summary(results):
    s = summarize(results)
    models = results["models"]
    w = max(len(c) for c in list(s["by_check"]) + ["check"]) + 2
    print("\nScore = PASS / (PASS + FAIL). Unknown and not-run are shown, never counted.\n")
    print("check".ljust(w) + "".join(m.split("/")[-1][:18].ljust(20) for m in models) + "separates?")
    for c, per in s["by_check"].items():
        cells = []
        for m in models:
            x = per[m]
            cell = f"{x['pass']}/{x['pass'] + x['fail']}" + (f" ?{x['unknown']}" if x["unknown"] else "")
            cells.append(cell.ljust(20))
        rates = [per[m]["rate"] for m in models if per[m]["rate"] is not None]
        all_runs = [x for m in models for x in [per[m]]]
        always = all(x["fail"] == 0 for x in all_runs)
        never = all(x["pass"] == 0 for x in all_runs)
        graded = any(x["pass"] + x["fail"] for x in all_runs)
        flag = "- (not graded)" if not graded else "no: always passes" if always else "no: never passes" if never else "yes" if len(set(rates)) > 1 or len(models) == 1 else "no: same rate"
        print(c.ljust(w) + "".join(cells) + flag)
    print()
    for m in models:
        x = s["by_model"][m]
        print(f"{m}: {x['rate']:.0%} of graded checks passed ({x['pass']}/{x['pass'] + x['fail']}), "
              f"{x['unknown']} unknown, {x['not_run']} not run" if x["rate"] is not None else f"{m}: nothing graded")
    for comp, per in s["unit"].items():
        print(f"unit/{comp}: " + ", ".join(f"{m.split('/')[-1]} {x['rate']:.0%}" for m, x in per.items()))
    uncached = uncached_checks(results)
    if uncached:
        print(f"\nNot graded, {NEEDS_KEY}: {', '.join(uncached)}. These judge checks aren't in cache/. "
              "Copy judge checks from solutions/checks.yaml (they replay), or add a key to .env to grade your own.")


def uncached_checks(results):
    return sorted({v["check"] for r in results["rows"] for v in r["verdicts"] if v.get("uncached")})


def save(results, name=None):
    name = name or datetime.now().strftime("%Y%m%d-%H%M%S")
    d = RUNS / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    return d


def load_run(name_or_path):
    p = Path(name_or_path)
    if p.is_dir():
        p = p / "results.json"
    elif not p.exists():
        p = RUNS / name_or_path / "results.json"
    return json.loads(p.read_text(encoding="utf-8"))
