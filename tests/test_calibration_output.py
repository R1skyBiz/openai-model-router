import pytest
from model_router.calibration.contracts import OutputContract
from model_router.calibration.output import compile_output_type

SCHEMA = {'type':'object','properties':{'count':{'type':'integer'}},'required':['count'],'additionalProperties':False}

def test_provider_wire_schema_and_local_validation_are_identical():
    output = compile_output_type(OutputContract(format='json',json_schema=SCHEMA))
    assert output.model_json_schema() == SCHEMA
    assert output.model_validate_json('{"count":3}').model_dump() == {'count':3}
    for raw in ['{"count":true}', '{"count":"3"}', '{"count":3,"extra":1}', '{}']:
        with pytest.raises(ValueError):
            output.model_validate_json(raw)
    # Existing OpenAI SDK strict schema conversion must not change the contract.
    from openai.lib._pydantic import to_strict_json_schema
    assert to_strict_json_schema(output) == SCHEMA


def test_open_schemas_fail_closed_instead_of_silent_sdk_rewrite():
    with pytest.raises(ValueError):
        compile_output_type(OutputContract(format='json',json_schema={'type':'object'}))
    with pytest.raises(ValueError):
        compile_output_type(OutputContract(format='json'))
    assert compile_output_type(OutputContract()) is None
