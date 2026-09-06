"""Pure capability and physical context feasibility checks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from model_router.core.contracts import Feasibility, Request


def check_capabilities(request: Request, model: Mapping[str, Any]) -> Feasibility:
    """Return hard capability/context exclusions for one catalog model.

    A missing or unverified capability is not support.  Context checks use the
    caller's complete input and expected output allowance; no truncation or
    cache assumption can make a physically impossible request feasible.
    """

    capabilities = model.get("capabilities", {})
    violations: list[str] = []
    rationale_codes: list[str] = []

    for requirement in request.requirements:
        if capabilities.get(requirement) is not True:
            _append_once(violations, requirement)

    if violations:
        rationale_codes.append("CAPABILITY_FILTER")

    context_violations = False
    maximum_output = model.get("max_output_tokens")
    if maximum_output is None or request.context.expected_output_tokens > maximum_output:
        _append_once(violations, "output_allowance")
        context_violations = True

    context_window = model.get("context_window_tokens")
    combined_tokens = request.context.input_tokens + request.context.expected_output_tokens
    if context_window is None or combined_tokens > context_window:
        _append_once(violations, "combined_context")
        context_violations = True

    if context_violations:
        rationale_codes.append("CONTEXT_CONSTRAINT")

    return Feasibility(violations=tuple(violations), rationale_codes=tuple(rationale_codes))


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
