"""Fakes limited to the documented public OpenAI Responses surface."""
from types import SimpleNamespace


def make_response(*, response_id="resp_fixture", status="completed", model="gpt-5.6-luna",
                  text="fixture output", parsed=None, input_tokens=100, cached_tokens=30,
                  cache_write_tokens=20, output_tokens=22, reasoning_tokens=7,
                  total_tokens=122, incomplete_reason=None, refusal=None):
    values = (input_tokens, cached_tokens, cache_write_tokens, output_tokens, reasoning_tokens, total_tokens)
    usage = None if all(v is None for v in values) else SimpleNamespace(
        input_tokens=input_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=cached_tokens,
                                              cache_write_tokens=cache_write_tokens),
        output_tokens=output_tokens,
        output_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
        total_tokens=total_tokens)
    content = []
    if text is not None:
        content.append(SimpleNamespace(type="output_text", text=text, parsed=parsed))
    if refusal is not None:
        content.append(SimpleNamespace(type="refusal", refusal=refusal))
    return SimpleNamespace(
        id=response_id, status=status, model=model,
        output=[SimpleNamespace(id="msg_fixture", type="message", role="assistant",
                                status=status, content=content)],
        output_text=text, output_parsed=parsed, usage=usage,
        incomplete_details=(SimpleNamespace(reason=incomplete_reason)
                            if incomplete_reason is not None else None))


def response_json(*, status="completed", text="transport output", response_id="resp_transport",
                  model="gpt-5.6-luna", error=None):
    return {
        "id": response_id, "object": "response", "created_at": 1788729600.0,
        "status": status, "model": model, "error": error,
        "output": [{"id": "msg_transport", "type": "message", "role": "assistant",
                    "status": status, "content": [{"type": "output_text", "text": text,
                                                     "annotations": []}]}],
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        "usage": {"input_tokens": 10,
                  "input_tokens_details": {"cached_tokens": 2, "cache_write_tokens": 3},
                  "output_tokens": 5,
                  "output_tokens_details": {"reasoning_tokens": 1}, "total_tokens": 15}}


class RawResponse:
    def __init__(self, envelope, parsed=None, parse_error=None):
        self.http_response = SimpleNamespace(json=lambda: envelope)
        self._parsed = parsed
        self._parse_error = parse_error
        self.parse_calls = 0

    def parse(self):
        self.parse_calls += 1
        if self._parse_error:
            raise self._parse_error
        return self._parsed


class _RawResponses:
    def __init__(self, owner): self.owner = owner
    def parse(self, **kwargs):
        self.owner.calls.append(("parse", kwargs))
        return self.owner.next_outcome(kwargs)


class _Responses:
    def __init__(self, owner):
        self.owner = owner
        self.with_raw_response = _RawResponses(owner)
    def create(self, **kwargs):
        self.owner.calls.append(("create", kwargs))
        return self.owner.next_outcome(kwargs)


class RecordingOpenAIClient:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes) if isinstance(outcomes, list) else [outcomes]
        self.option_calls = []
        self.calls = []
        self.responses = _Responses(self)
    def with_options(self, **kwargs):
        self.option_calls.append(kwargs)
        return self
    def next_outcome(self, kwargs):
        if not self._outcomes: raise AssertionError("fake OpenAI response script exhausted")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException): raise outcome
        if callable(outcome): return outcome(kwargs)
        return outcome
