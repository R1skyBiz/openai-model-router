"""Allowlisted serialization for durable execution telemetry.

The core records mark in-memory content with Pydantic ``exclude=True``.  Keeping
serialization here gives persistence and future transports one reviewed path and
prevents callers from accidentally using ``__dict__`` on those records.
"""

from __future__ import annotations

from typing import Any

from model_router.core.execution_contracts import ExecutionEvent, TaskResult


def event_payload(event: ExecutionEvent) -> dict[str, Any]:
    """Return the complete, content-free event envelope."""

    return event.model_dump(mode="json")


def task_payload(task: TaskResult) -> dict[str, Any]:
    """Return a task snapshot with all in-memory-only fields excluded."""

    return task.model_dump(mode="json")
