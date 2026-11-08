"""Online evals and capture: production feeds the suite.

`grade_logs` runs the suite's checks on logged conversations as they happened (no replay),
off the request path. `capture` turns one logged conversation into a regression case.
"""

import json
import random
import re
from pathlib import Path

import yaml

from bot.agent import redact_pii
from evals.core import SUITE, checks_for, grade, load_checks


def log_to_transcript(conv):
    transcript, pending = [], None
    for m in conv["messages"]:
        if m["role"] == "customer":
            pending = {"user": m["content"], "tools": m.get("tools", []), "guardrail": None}
        elif m["role"] == "bot" and pending:
            transcript.append({**pending, "reply": m["content"]})
            pending = None
    return transcript


def as_case(conv):
    return {"id": conv["id"], "family": "production", "user_id": conv["user_id"], "today": conv["date"],
            "policy": conv.get("policy", []), "judge_notes": conv.get("agent_note", ""), "checks": []}


def grade_logs(path, sample, checks_path, judge_model, seed=0):
    convs = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    if sample and sample < len(convs):
        convs = random.Random(seed).sample(convs, sample)
    suite_checks = load_checks(checks_path)
    rows = []
    for conv in convs:
        case = as_case(conv)
        result = {"status": "valid", "error": None, "transcript": log_to_transcript(conv)}
        verdicts = grade(case, result, checks_for(case, suite_checks), judge_model)
        rows.append({"id": conv["id"], "outcome": conv.get("outcome"), "verdicts": verdicts})
    return rows


def print_logs(rows):
    print(f"\nGraded {len(rows)} logged conversations (no replay).\n")
    for r in rows:
        fails = [v for v in r["verdicts"] if v["verdict"] == "FAIL"]
        mark = "FAIL" if fails else "ok  "
        print(f"{mark} {r['id']}" + (f"  [{r['outcome']}]" if r["outcome"] else ""))
        for v in fails:
            print(f"       {v['check']}: {v['evidence']}")
    flagged = [r["id"] for r in rows if any(v["verdict"] == "FAIL" for v in r["verdicts"]) or r["outcome"]]
    if flagged:
        print("\nCapture the ones worth keeping:  evals capture production/conversations.jsonl --id " + flagged[0])


def capture(path, conv_id=None):
    p = Path(path)
    if p.suffix == ".jsonl":
        convs = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        conv = next(c for c in convs if c["id"] == conv_id) if conv_id else convs[0]
    else:
        conv = json.loads(p.read_text(encoding="utf-8"))
    turns = [redact_pii(m["content"]) for m in conv["messages"] if m["role"] == "customer"]
    slug = re.sub(r"[^a-z0-9]+", "-", conv["id"].lower()).strip("-")
    case = {
        "id": f"p-{slug}",
        "family": "production",
        "source": f"captured from {conv['id']} ({conv.get('outcome', 'logged')}), PII redacted",
        "user_id": conv["user_id"],
        "today": conv["date"],
        "turns": turns,
        "policy": conv.get("policy", []),
        "judge_notes": conv.get("agent_note", "TODO: what should the bot have done?"),
        "checks": [{
            "id": "todo_from_agent_note",
            "kind": "judge",
            "status": "candidate",
            "question": "TODO: turn the agent's note into one yes/no question.\n"
                        f"Agent's note: \"{conv.get('agent_note', '')}\"\nPASS if ...\nFAIL if ...\n",
        }],
    }
    out = SUITE / "cases" / f"{case['id']}.yaml"
    out.write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
    return out
