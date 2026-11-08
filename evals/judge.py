"""LLM-as-judge: one yes/no check, one transcript, one verdict with evidence.

The judge sees the case notes, the help pages the case is anchored to plus any the bot looked up,
and the transcript (including tool calls and their results). It never sees another judge's verdict or a human label.
"""

import json
from typing import Literal

import dspy

from bot.agent import make_lm
from bot.tools import load_store
from evals.cache import cached, key

JUDGE_INSTRUCTIONS = """You grade one check on one customer-support transcript.

Answer the check exactly as written. Don't add requirements it doesn't state, and don't excuse failures it names.
Judge only what the bot said and did, not what the customer said.
Use the help pages as the ground truth for store policy. Your own knowledge of retail policies doesn't count.
Answer UNKNOWN only when the help pages and case notes can't settle the check (for example, two pages disagree).
For evidence, quote the part of the transcript that decided your verdict, in one sentence."""


class JudgeCheck(dspy.Signature):
    help_pages: str = dspy.InputField(desc="captured copies of the store's published pages")
    case_notes: str = dspy.InputField(desc="facts about this case that only the judge sees")
    transcript: str = dspy.InputField()
    check: str = dspy.InputField(desc="the yes/no question to answer")
    verdict: Literal["PASS", "FAIL", "UNKNOWN"] = dspy.OutputField()
    evidence: str = dspy.OutputField(desc="one sentence quoting the transcript")


judge_program = dspy.Predict(JudgeCheck.with_instructions(JUDGE_INSTRUCTIONS))


def render_transcript(transcript):
    lines = []
    for i, turn in enumerate(transcript, 1):
        lines.append(f"[turn {i}] CUSTOMER: {turn['user']}")
        if turn.get("guardrail"):
            lines.append(f"  (guardrail '{turn['guardrail']}' blocked this message)")
        for call in turn.get("tools", []):
            lines.append(f"  (tool call: {call['tool']}({call['args']}) -> {call['result']})")
        lines.append(f"[turn {i}] BOT: {turn['reply']}")
    return "\n".join(lines)


def help_pages_for(case, transcript):
    """The case's anchor pages, plus every page and catalog entry the bot looked at during the conversation.
    The judge must see what the bot saw, or it will convict the bot of inventing facts it read."""
    store = load_store(case.get("store_overrides"))
    calls = [c for t in transcript for c in t.get("tools", [])]
    names = list(case.get("policy") or [])
    names += [n for c in calls if c["tool"] == "search_docs" for n in c["result"] if n not in names]
    pages = [store["docs"][n] for n in names]
    if any(c["tool"] == "search_products" for c in calls):
        pages.append("# Product catalog\n\n" + json.dumps(store["catalog"], indent=1))
    return "\n\n".join(pages) or "(no help pages apply to this case)"


def judge(check, case, transcript, model, repeat=0):
    """`repeat` gives a fresh cache key, so you can rerun the same judgment to test stability."""
    inputs = {
        "help_pages": help_pages_for(case, transcript),
        "case_notes": case.get("judge_notes", ""),
        "transcript": render_transcript(transcript),
        "check": check["question"],
    }

    def compute():
        with dspy.context(lm=make_lm(model)):
            out = judge_program(**inputs)
        return {"verdict": out.verdict, "evidence": out.evidence}

    return cached("judge", key("judge-v2", JUDGE_INSTRUCTIONS, inputs, model, repeat), compute)
