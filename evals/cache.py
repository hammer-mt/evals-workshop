"""Content-addressed cache. A key is a hash of everything that could change the result.

Change the prompt, the model, the case or the check text and you get a new key, so only
the work that changed gets rerun. Commit cache/ and anyone can replay your runs with no API key.
"""

import hashlib
import json
import os
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


class CacheMiss(RuntimeError):
    pass


def key(*parts):
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def offline():
    """Offline when EVALS_OFFLINE=1, or when no provider key is set."""
    if os.getenv("EVALS_OFFLINE") == "1":
        return True
    return not any(os.getenv(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"))


def cached(kind, k, compute):
    path = CACHE_DIR / kind / f"{k}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if offline():
        raise CacheMiss(f"No cached {kind} for key {k}, and no API key is set (see the Setup section of README.md).")
    value = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, ensure_ascii=False), encoding="utf-8")
    return value
