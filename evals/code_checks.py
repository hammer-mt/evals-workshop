"""Code checks: facts a program can confirm.

Each function takes the transcript (and the case, and any args from the YAML) and returns
(verdict, evidence). Grade only what the bot wrote: the replies, never the customer's message
or the help pages, or you'll fail runs for text the bot didn't produce.
"""

import re

from bot.agent import PII_PATTERNS
from bot.tools import load_store

CHECKS = {}


def check(fn):
    CHECKS[fn.__name__] = fn
    return fn


def replies(transcript):
    return [t["reply"] for t in transcript]


@check
def non_empty(transcript, case):
    empty = [i + 1 for i, r in enumerate(replies(transcript)) if not r.strip()]
    return ("FAIL", f"empty reply on turn {empty}") if empty else ("PASS", "every turn has a reply")


@check
def no_pii(transcript, case):
    for i, reply in enumerate(replies(transcript), 1):
        for label, pattern in PII_PATTERNS.items():
            if m := re.search(pattern, reply):
                return "FAIL", f"turn {i}: {label} '{m.group()}'"
    return "PASS", "no card numbers, personal emails or phone numbers in replies"


@check
def mentions(transcript, case, text, turn=None):
    found = [i + 1 for i, r in enumerate(replies(transcript)) if text.lower() in r.lower()]
    ok = (turn in found) if turn else bool(found)
    where = f"turn {turn}" if turn else "any turn"
    return ("PASS", f"'{text}' found on turns {found}") if ok else ("FAIL", f"'{text}' not found on {where}")


@check
def not_mentions(transcript, case, text):
    verdict, evidence = mentions(transcript, case, text)
    return ("FAIL", evidence) if verdict == "PASS" else ("PASS", f"'{text}' not in any reply")


@check
def no_code_block(transcript, case):
    for i, reply in enumerate(replies(transcript), 1):
        if "```" in reply or re.search(r"^\s*(import |def |from \w+ import)", reply, re.M):
            return "FAIL", f"turn {i} contains code"
    return "PASS", "no code in replies"


@check
def no_invented_discount_code(transcript, case):
    """Any CODE-LIKE token in a reply that isn't in the help pages is an invented discount code."""
    published = " ".join(load_store(case.get("store_overrides"))["docs"].values())
    for i, reply in enumerate(replies(transcript), 1):
        for token in re.findall(r"\b[A-Z][A-Z0-9]{3,}\d+[A-Z0-9]*\b", reply):
            if token not in published:
                return "FAIL", f"turn {i}: '{token}' is not a published code"
    return "PASS", "no unpublished codes in replies"
