"""Stable, content-complete hashes for task idempotency."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel

from model_router.core.contracts import Classification, Request
from model_router.core.execution_contracts import ExecutionControls, ToolCall


def request_digest(
    request: Request,
    controls: ExecutionControls,
    supplied_classification: Classification | None = None,
) -> str:
    """Hash every logical request input while excluding correlation identifiers."""

    request_values = request.model_dump(mode="python")
    request_values.pop("task_id", None)
    request_values.pop("trace_id", None)
    # ``input`` is excluded from normal serialization, so include it explicitly.
    request_values["input"] = request.input

    controls_values = controls.model_dump(mode="python")
    controls_values["idempotency_key"] = controls.idempotency_key
    controls_values["tool_calls"] = [_tool_values(call) for call in controls.tool_calls]
    controls_values["output_schema"] = (
        controls.output_type.model_json_schema() if controls.output_type is not None else None
    )

    payload = {
        "request": request_values,
        "controls": controls_values,
        "supplied_classification": supplied_classification,
    }
    return _hash(payload)


def scoped_key_digest(scope: str, key: str | None) -> str | None:
    """Hash an idempotency key together with its repository/application scope."""

    if key is None:
        return None
    if not isinstance(scope, str) or not scope or not isinstance(key, str) or not key:
        raise ValueError("scope and idempotency key must be nonempty strings")
    return _hash({"scope": scope, "idempotency_key": key})


def key_digest(scope: str, key: str | None) -> str | None:
    """Compatibility spelling for repository composition."""

    return scoped_key_digest(scope, key)


def idempotency_key_digest(scope: str, key: str | None) -> str | None:
    """Explicit spelling used by callers that keep multiple digests."""

    return scoped_key_digest(scope, key)


def _tool_values(call: ToolCall) -> dict[str, Any]:
    values = call.model_dump(mode="python")
    values["idempotency_key"] = call.idempotency_key
    values["arguments"] = call.arguments
    return values


def _hash(value: object) -> str:
    encoded = json.dumps(
        _canonical(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonical(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        canonical = [_canonical(item) for item in value]
        return sorted(canonical, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, (datetime, date)):
        return {"$datetime": value.isoformat()}
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, bytes):
        return {"$bytes": value.hex()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported value in idempotency digest: {type(value).__name__}")


__all__ = [
    "idempotency_key_digest",
    "key_digest",
    "request_digest",
    "scoped_key_digest",
]
