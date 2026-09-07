"""Separate operational config; never activates or edits the routing policy."""
from pathlib import Path
from model_router.core.phase4_contracts import Phase4Config
from model_router.core.configuration import _load_yaml


def load_phase4(path, bundle):
    config = Phase4Config.model_validate(_load_yaml(Path(path)))
    validate_phase4(config, bundle)
    return config


def validate_phase4(config, bundle):
    for binding in config.evaluators:
        model = bundle.catalog['models'].get(binding.model_alias)
        if model is None or binding.reasoning_effort not in model['reasoning_efforts']:
            raise ValueError('unsupported evaluator model/effort binding')
        if not model['availability']['configured_enabled'] or any(model['capabilities'].get(c) is not True for c in ('text_input', 'text_output', 'structured_outputs')):
            raise ValueError('evaluator capability unavailable')
        if binding.max_output_tokens > model['max_output_tokens'] or binding.max_input_tokens + binding.max_output_tokens > model['context_window_tokens']:
            raise ValueError('evaluator bounds exceed model capacity')
    return config
