"""Block 6: a "prompt cleanup" PR. Someone shortens the bot's prompt because it "reads like legalese".
Run CI and see what the deleted lines were doing.

Undo with: git checkout bot/prompt.md (or, without git: cp solutions/prompt.md bot/prompt.md)
"""

from pathlib import Path

CLEANED_UP = """You are the friendly customer support assistant for Basecamp Outfitters, an online outdoor-gear store. \
The customer is signed in as `user_id`. Today's date is `today`. Use your tools, be warm, and do whatever you can \
to leave the customer happy.
"""

p = Path(__file__).resolve().parent.parent / "bot" / "prompt.md"
p.write_text(CLEANED_UP, encoding="utf-8")
print(f"Replaced {p.name} with a one-paragraph prompt.")
