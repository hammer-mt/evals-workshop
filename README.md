# Building an Eval Suite Your Team Will Actually Run

Workshop repo for ODSC AI NYC 2026 · Mike Taylor

An eval is past work, saved and replayed against a new model or prompt, then graded. This repo does that for a customer-support bot in about 900 lines of plain Python, with no eval framework to learn.

The bot is the customer-service agent from Chapter 9 of [*Context Engineering with DSPy*](https://www.oreilly.com/library/view/context-engineering-with/0642572261603/), with the Chapter 4 ticket router in front of it.

## Setup

Do this before the session if you can: the install is about 75 MB.

**1. Install uv** (it installs Python for you):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                  # macOS / Linux
```
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"        # Windows
```

**2. Clone and check:**

```bash
git clone https://github.com/hammer-mt/evals-workshop && cd evals-workshop
uv sync
uv run evals check-setup
```

The last line should be `Setup OK.`

**No API key? That's fine.** Every step replays from `cache/` without a key, except grading judge checks you write yourself. Those show as "not graded (needs an API key)" while everything else still grades. Copy judge checks from `solutions/checks.yaml` and they replay too. The cached runs are Claude Haiku 5.5 vs Sonnet 5.5, 3 runs each, judged by Opus 5.5.

To run live, copy `.env.example` to `.env` and add `ANTHROPIC_API_KEY`. Any provider [LiteLLM](https://docs.litellm.ai/docs/providers) supports works: set `EVALS_MODELS` and `EVALS_JUDGE` to that provider's model names.

**If it fails:**
- `uv: command not found`: open a new terminal so the installer's PATH change applies.
- `make: command not found` (Windows, most often): use the "without make" column below. `make` is only a shortcut.
- "No cached runs" on a step you didn't change: run `git status`. Any edit to the prompt, a case or a help page changes the cache key; `git diff` shows what changed.

## The steps

| Block | With make | Without make | What you do |
|---|---|---|---|
| 1 | `make setup` | `uv sync` then `uv run evals check-setup` | Install and check what you can run |
| 2 | `make run` | `uv run evals run --name workshop --runs 3 --unit` | Replay 17 cases on two models and open `runs/workshop/index.html` |
| 2-3 | (read) | (read) | Read h01 and g02 in the viewer and write 3-5 reactions in `notes.md` |
| 4 | edit `suites/support/checks.yaml`, `make run` | same edit, then the Block 2 command | Write 1 code check and copy 2 judge checks from `solutions/checks.yaml` (with a key, write your own) |
| 4 | `make run-solution` | `uv run evals run --name solution --runs 3 --unit --checks solutions/checks.yaml` | The worked answer |
| 5 | viewer → Label mode, then `make calibrate` | `uv run evals calibrate solution --labels "labels/*.jsonl" --repeat 2` | Label the h01 verdicts blind, then measure the judge against you (see `solutions/README.md`) |
| 6 | `make break`, `make ci` | `uv run python scripts/break_prompt.py`, then `uv run evals ci --tier pr --checks solutions/checks.yaml --baseline baseline-pr.json` | Ship a "prompt cleanup" PR and watch the PR tier catch what it broke. Undo with `git checkout bot/prompt.md` |
| 7 | `make online`, `make capture` | `uv run evals online production/conversations.jsonl --checks solutions/checks.yaml`, then `uv run evals capture production/conversations.jsonl --id conv-1042` | Grade production logs and turn a failure into a regression case |

## Using the CI workflow in your own fork

1. Fork the repo and enable Actions on the fork (Actions tab → "I understand my workflows").
2. Add `ANTHROPIC_API_KEY` under Settings → Secrets and variables → Actions. Optionally add `EVALS_MODELS` and `EVALS_JUDGE` as variables.
3. Open a PR that edits `bot/prompt.md`. The PR tier comments its report on the PR. Without the secret, anything not in `cache/` fails the build with a report that says so: an eval that didn't run must not go green.

## What's where

```
bot/                     the support bot (DSPy): agent, router, guardrails, prompt.md
store/                   frozen snapshot of the store's help pages, orders and catalog (the mocked tools read this)
suites/support/cases/    17 scripted conversations, one YAML file each
suites/support/checks.yaml   suite-level checks (starters you'll replace)
suites/unit/             router and injection-detector test sets (unit evals, exact match)
solutions/checks.yaml    worked-answer checks
evals/                   the harness: core.py (replay and grade), judge.py, code_checks.py,
                         calibrate.py, ci.py, production.py, viewer.html
production/              sample production logs (fictional)
cache/                   cached runs and judge verdicts, so no key is needed
.github/workflows/       two-tier CI: PR tier on every PR, nightly tier on a schedule
```

## Ideas the repo is built on

**Cases**
- **A case is a scripted conversation**, follow-ups included, because the second message is where agents break. For example, refusing to paste the instructions and then summarizing them as bullets (`r02`).
- **Cases are anchored to captured policy pages** (`store/docs/`). The judge grades against those pages, not against its own idea of retail policy.
- **Paired cases change one fact.** `g01` and `g02` are the same return request; only "engraved" differs, so the answer should change.
- **Some failures are your website's fault.** In `g04`, the deals page still advertises a promotion the terms say has ended.

**Grading**
- **Checks are yes/no and test one thing each**, with what PASS and FAIL look like. Use code for facts and a judge for judgment.
- **The verdict can be UNKNOWN.** A run can also be invalid. Neither counts as a pass or a fail.

**Calibration and CI**
- **Audit the auditor.** You label blind, without seeing the judge's verdict. `evals calibrate` counts false accusations and misses separately, on a holdout split.
- **CI gates on regressions against a baseline**, not on 100%. The PR baseline is the 3-run nightly result for the smoke cases, so "never failed" means it held in all 3 runs. A failure on a never-failed check is rerun once and blocks only if it fails again. Unchanged work is cached by content hash, so it costs nothing to rerun.
- **An eval that didn't run fails the build.** Invalid runs and checks that couldn't be graded are regressions, not "0/0, no change".

## Commands

```
evals run [--models a,b] [--runs 3] [--cases id,id] [--tags smoke] [--checks file] [--unit]
evals view <run>
evals calibrate <run> --labels labels/*.jsonl [--repeat 2]
evals baseline <run> [--tags smoke] --out baseline-pr.json
evals ci --tier pr|nightly --baseline baseline-pr.json [--allow 1] [--no-rerun]
evals online production/conversations.jsonl [--sample 20]
evals capture production/conversations.jsonl --id conv-1042
```

## Changes from the book's listings

- Tools read from a frozen store snapshot, so replays are deterministic.
- The agent takes conversation history (`dspy.History`), so cases can script follow-ups.
- PII redaction uses regexes instead of Presidio, to avoid a 400 MB spaCy download in a workshop.
- The router's departments are the store's teams (orders, returns, products, account), not the book's SaaS ones.
- No output field is named `reasoning` or `thought`, and the agent's plans aren't replayed into its trajectory. Claude Sonnet 5.5 refuses those requests (`stop_reason: refusal`). The first Sonnet runs came back empty and the harness marked them invalid rather than FAIL, which is how we found it. `bot/agent.py` has `think()` and `PlanReAct`, which are ChainOfThought and ReAct with the fields renamed.

## License

MIT. The bot is adapted from the book's code at [hammer-mt/context-engineering-dspy-book](https://github.com/hammer-mt/context-engineering-dspy-book).
