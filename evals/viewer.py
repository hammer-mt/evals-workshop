"""Write a self-contained HTML viewer for a run: transcripts side by side, verdicts with
evidence, and a blind label mode that exports labels/*.jsonl for `evals calibrate`."""

import json
from pathlib import Path

from evals.core import load_cases, load_checks, summarize

TEMPLATE = Path(__file__).with_name("viewer.html")


def write_viewer(results, out_dir):
    cases = {c["id"]: c for c in load_cases()}
    questions = {c["id"]: c.get("question", f"code: {c.get('fn')}({c.get('args', '')})") for c in load_checks(results["checks_file"])}
    for c in cases.values():
        for chk in c.get("checks", []):
            questions[chk["id"]] = chk.get("question", f"code: {chk.get('fn')}({chk.get('args', '')})")
    data = {
        "name": Path(out_dir).name,
        "results": results,
        "summary": summarize(results),
        "cases": {k: {f: v.get(f) for f in ("id", "family", "pair", "policy", "judge_notes", "today", "user_id")} for k, v in cases.items()},
        "questions": questions,
    }
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    path = Path(out_dir) / "index.html"
    path.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", blob), encoding="utf-8")
    return path
