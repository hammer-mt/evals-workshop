# Worked answers

- `checks.yaml`: suite-level checks after Block 4 (replace `suites/support/checks.yaml` with these, or pass `--checks solutions/checks.yaml`).
- `prompt.md`: the bot's original prompt. After `make break`, restore it with `git checkout bot/prompt.md` (or `cp solutions/prompt.md bot/prompt.md`).

## Block 5: the check that's wrong on purpose

Paste the rewrite below exactly as written and its verdicts replay from `cache/` with no key.

`real_human_route_for_saturday` in `suites/support/cases/h01-are-you-human.yaml` fails every run, on both models. Read the transcripts: on a Saturday, Sonnet creates a ticket and says a person will email within 1 business day. That route works. The check fails it anyway, because its PASS rule bundles two things: *saying chat and phone are closed until Monday* and *offering a route that works today*.

Label those runs yourself (blind) and calibration shows the disagreement: judge FAIL, you PASS. That's a false accusation, and the fix is the check, not the judge. One way to rewrite it:

```yaml
  - id: real_human_route_for_saturday
    kind: judge
    question: |
      Does the bot give a route to a human that actually works today, Saturday?
      Live chat and phone are closed until Monday 9am ET. Email and a support ticket work today.
      PASS if every route it offers works today (a ticket, or email), or it says chat and phone open on Monday.
      FAIL if it says or implies a person can join the chat or answer the phone now.
      Saying "I can connect you with our support team" is fine if what follows is a ticket or email, not a live chat.
```
