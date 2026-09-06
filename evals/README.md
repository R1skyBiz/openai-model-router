# Evaluations

This directory holds offline routing, classification, escalation, and
regression cases. Evaluation cases are JSON Lines files so they can grow
incrementally and remain easy to inspect.

Run the bootstrap validator with:

```bash
uv run python evals/run_local.py
```

The runner currently validates JSONL syntax only. Graders and result schemas
will be defined with the Phase 1 routing contracts. No OpenAI API key is needed.
