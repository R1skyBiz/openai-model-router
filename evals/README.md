# Evaluations

This directory holds offline routing, classification, escalation, and
regression cases. Evaluation cases are JSON Lines files so they can grow
incrementally and remain easy to inspect.

Run the bootstrap validator with:

```bash
uv run python evals/run_local.py
```

The runner currently validates JSONL syntax only. It does not grade routing
behavior; empty case files are valid scaffold input. No OpenAI API key is needed.

The architecture contract defines the [eval philosophy](../docs/routing-policy-v1.md#evals-and-activation)
and [phase gates](../docs/implementation-spec-v1.md). The next dedicated eval step
will define acceptable model/effort envelopes and deterministic hard-constraint
graders. Before production v1, at least 100 cases must cover all task families,
thresholds, budgets, tool/provider failures, long context, escalation and
must-not-use-Astra scenarios. The architecture-contract task does not generate
that corpus or implement its graders.
