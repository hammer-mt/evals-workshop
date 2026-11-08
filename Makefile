# Each target is one workshop step. `make help` lists them.
CHECKS ?= solutions/checks.yaml

help:            ## list the steps
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/\t/'

setup:           ## Block 1: install and check what you can run
	uv sync
	uv run evals check-setup

run:             ## Block 2: replay 17 cases x 2 models x 3 runs, graded with the starter checks
	uv run evals run --name workshop --runs 3 --unit

run-solution:    ## Block 4: the same run, graded with the worked-answer checks
	uv run evals run --name solution --runs 3 --unit --checks $(CHECKS)

calibrate:       ## Block 5: judge vs your labels (download labels.jsonl from the viewer into labels/)
	uv run evals calibrate solution --labels 'labels/*.jsonl' --repeat 2

ci:              ## Block 6: the PR tier, as CI runs it
	uv run evals ci --tier pr --checks $(CHECKS) --baseline baseline-pr.json

break:           ## Block 6: a "prompt cleanup" PR (undo: git checkout bot/prompt.md)
	uv run python scripts/break_prompt.py

online:          ## Block 7: grade logged production conversations
	uv run evals online production/conversations.jsonl --checks $(CHECKS)

capture:         ## Block 7: turn an escalated conversation into a regression case
	uv run evals capture production/conversations.jsonl --id conv-1042

test:            ## harness tests (no model calls)
	uv run --group dev pytest -q

baseline:        ## rebuild both CI baselines from the 3-run solution results
	uv run evals baseline solution --tags smoke --out baseline-pr.json
	uv run evals baseline solution --out baseline-nightly.json
