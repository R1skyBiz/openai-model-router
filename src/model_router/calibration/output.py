"""Faithful structured-output schemas at the existing provider boundary."""
from __future__ import annotations
from collections.abc import Mapping
from copy import deepcopy
import json
from pydantic import RootModel, model_validator
from model_router.core.contracts import thaw
from .contracts import OutputContract


def _strict_wire(schema):
    """Reject schemas which the provider SDK would silently tighten or rewrite."""
    if not isinstance(schema, Mapping):
        raise ValueError('structured output requires an object schema')
    if '$ref' in schema or 'default' in schema:
        raise ValueError('unsupported structured output schema keyword')
    kind = schema.get('type')
    if kind == 'object':
        props = schema.get('properties')
        required = schema.get('required')
        if (not isinstance(props, Mapping) or not isinstance(required, (tuple, list)) or
                set(props) != set(required) or schema.get('additionalProperties') is not False):
            raise ValueError('structured object must have explicit required properties and forbid extras')
        for value in props.values():
            _strict_wire(value)
    elif kind == 'array':
        if 'items' not in schema:
            raise ValueError('structured array requires item schema')
        _strict_wire(schema['items'])
    elif kind not in {'string', 'number', 'integer', 'boolean', 'null'}:
        raise ValueError('unsupported structured type')
    if any(key in schema for key in ('allOf', 'oneOf', 'anyOf', 'not')):
        raise ValueError('structured schema combinators are unsupported in Phase 1')


def compile_output_type(contract: OutputContract):
    if contract.format != 'json':
        if contract.json_schema is not None:
            raise ValueError('text output cannot carry a JSON schema')
        return None
    if contract.json_schema is None:
        raise ValueError('JSON output requires an explicit schema')
    from .grading import validate_schema, schema_matches
    schema = json.loads(json.dumps(thaw(contract.json_schema)))
    _strict_wire(schema)
    validate_schema(schema)
    if schema.get('type') != 'object':
        raise ValueError('provider structured output requires an object root')

    class CalibrationOutput(RootModel[dict]):
        @model_validator(mode='after')
        def matches_contract(self):
            if not schema_matches(self.root, schema):
                raise ValueError('output does not match the pinned contract')
            return self

        @classmethod
        def model_json_schema(cls, *args, **kwargs):
            return deepcopy(schema)

    return CalibrationOutput
