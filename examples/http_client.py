"""Authenticated route preview; no execution or provider call."""
import json
import os
from urllib.request import Request, urlopen


def preview(base_url: str, token: str) -> dict:
    payload = {
        'request': {'task_id': 'sample-preview-1', 'trace_id': 'sample-preview-trace-1',
                    'input': 'Convert these labels to lowercase.', 'consequence': 'low',
                    'requirements': ['text_input', 'text_output'],
                    'context': {'input_tokens': 100, 'expected_output_tokens': 50}},
        'classification': {'task_family': 'transform', 'confidence': 1.0,
                           'provenance': 'application-supplied',
                           'components': {'reasoning_depth': 0, 'step_dependency': 0,
                                          'context_synthesis': 0, 'technical_precision': 0,
                                          'ambiguity': 0, 'tool_orchestration': 0,
                                          'reliability_requirement': 0}}
    }
    request = Request(base_url.rstrip('/') + '/v1/route', method='POST',
        data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


if __name__ == '__main__':
    print(json.dumps(preview(os.environ.get('MODEL_ROUTER_URL', 'http://127.0.0.1:8000'),
                            os.environ['MODEL_ROUTER_APP_TOKEN']), indent=2))
