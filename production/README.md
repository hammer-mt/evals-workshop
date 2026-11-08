# Sample production logs

`conversations.jsonl` is fictional sample data: logged conversations from the support bot as it might run in production, with the outcome a support agent recorded (escalated, thumbs-down) and the agent's note.

Use it for Block 7:

    evals online production/conversations.jsonl --checks solutions/checks.yaml
    evals capture production/conversations.jsonl --id conv-1042
