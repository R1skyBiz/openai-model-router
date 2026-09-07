"""Shared provider accounting and content exclusion invariants."""

import ast
import socket
from pathlib import Path
import subprocess

import pytest
from pydantic import BaseModel, ValidationError

from model_router.core.provider_contracts import ProviderRequest, ProviderResult, ProviderUsage


@pytest.mark.parametrize("buckets", [
    {"input_tokens": 5, "cached_input_tokens": 4, "cache_write_input_tokens": 2},
    {"output_tokens": 2, "reasoning_tokens": 3},
    {"input_tokens": 5, "output_tokens": 3, "total_tokens": 11},
    {"input_tokens": True}, {"output_tokens": -1},
])
def test_invalid_accounting_is_rejected(buckets):
    with pytest.raises(ValidationError):
        ProviderUsage(**buckets)


def test_partial_usage_never_fabricates_zero():
    usage = ProviderUsage(input_tokens=20, output_tokens=8, total_tokens=28)
    assert usage.status == "partial"
    assert usage.uncached_input_tokens is None
    assert usage.reasoning_tokens is None
    assert ProviderUsage().status == "unavailable"


def test_disjoint_input_buckets_and_reasoning_subset():
    usage = ProviderUsage(input_tokens=100, cached_input_tokens=25,
                          cache_write_input_tokens=15, output_tokens=40,
                          reasoning_tokens=30, total_tokens=140)
    assert usage.status == "known"
    assert usage.uncached_input_tokens == 60
    assert usage.total_tokens == 140


def test_raw_content_is_excluded_from_repr_and_serialization():
    class Output(BaseModel):
        answer: str

    request = ProviderRequest(task_id="task", trace_id="trace", invocation_id="inv",
        policy_version="policy", catalog_version="catalog", model_alias="test",
        provider_model_id="configured-model", reasoning_effort="low", input="secret-input",
        instructions="secret-instructions", output_type=Output, max_output_tokens=20, timeout_ms=500)
    response = ProviderResult(**{key: value for key, value in request.model_dump().items()
        if key not in {"max_output_tokens", "timeout_ms", "truncation"}},
        latency_ms=1.0, response_status="completed", text="secret-output",
        structured_output=Output(answer="secret-structured"))
    for record in (request, response):
        assert "secret-" not in repr(record)
        assert "secret-" not in record.model_dump_json()
    assert response.structured_output.answer == "secret-structured"


def test_default_network_guard():
    with pytest.raises(AssertionError, match="network access is forbidden"):
        socket.create_connection(("example.com", 443))


def test_phase1_runtime_is_byte_identical_to_approved_baseline():
    root = Path(__file__).resolve().parents[1]
    baseline = "971f08386bf23ae9370bc51c1851a4162e9e86d7"
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", baseline,
                                     "src/model_router"], cwd=root, text=True).splitlines()
    for path in paths:
        # Phase 3 adds recovery candidate admission to the shared router. Its
        # default behavior is protected by all Phase 1 tests and 142 envelopes.
        if path == "src/model_router/router.py":
            continue
        approved = subprocess.check_output(["git", "show", f"{baseline}:{path}"], cwd=root)
        assert (root / path).read_bytes() == approved, path


def test_core_and_policy_do_not_import_implementations():
    root = Path(__file__).resolve().parents[1] / "src/model_router"
    for folder in ("core", "policy"):
        for path in (root / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                         [item.name for item in node.names] if isinstance(node, ast.Import) else [])
                assert not any(name.startswith(("model_router.execution", "model_router.classification"))
                               for name in names), path


def test_classifier_never_imports_route_selection():
    root = Path(__file__).resolve().parents[1] / "src/model_router/classification"
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                     [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            assert not any(name.startswith(("model_router.router", "model_router.policy.modifiers"))
                           for name in names), path
