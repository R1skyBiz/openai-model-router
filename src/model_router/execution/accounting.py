"""Price normalized usage against the immutable invocation tariff."""
from model_router.core.contracts import Context, ValidationRequirements
from model_router.policy.costs import estimate_cost

def provider_cost(request, outcome, bundle, environment):
    usage = outcome.usage
    if any(value is None for value in (usage.input_tokens, usage.cached_input_tokens,
                                       usage.cache_write_input_tokens, usage.output_tokens)):
        return None
    model = bundle.catalog['models'].get(outcome.model_alias)
    if model is None:
        return None
    measured = request.model_copy(update={'side_effecting_tool': False, 'context': Context(
        input_tokens=usage.input_tokens, expected_output_tokens=usage.output_tokens,
        cached_input_tokens=usage.cached_input_tokens, cache_write_tokens=usage.cache_write_input_tokens,
        cache_evidence=True)})
    env = environment.model_copy(update={'required_tool_charge': False})
    validation = ValidationRequirements(level='V0', profiles=('V0',), checks=(), evidence='usage')
    quote = estimate_cost(measured, model, env, validation, currency=bundle.catalog['currency'])
    return quote.amount
