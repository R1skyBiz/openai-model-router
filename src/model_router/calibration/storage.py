"""Private, append-only filesystem persistence for calibration evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import fcntl
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from model_router.calibration.contracts import CalibrationRun, RunManifest
from model_router.calibration.corpus import require_safe_identifier


class CalibrationStorageError(RuntimeError):
    """Calibration evidence could not be persisted without weakening guarantees."""


_EVENT_KEYS = frozenset(
    {
        "kind",
        "run_id",
        "strategy_run_id",
        "call_id",
        "purpose",
        "status",
        "cost_usd",
        "failure_type",
        "case_id",
        "strategy",
        "execution_status",
        "reason",
        "attempt_number",
        "input_sha256",
        "output_sha256",
        "latency_ms",
        "model",
        "effort",
        "pricing_version",
    }
)
_EVENT_IDENTIFIER_KEYS = _EVENT_KEYS - {"cost_usd", "latency_ms", "attempt_number"}
_SECRET_FRAGMENTS = (
    "secret",
    "password",
    "credential",
    "authorization",
    "api_key",
    "access_token",
    "refresh_token",
    "private_key",
    "bearer_token",
)
_RAW_KEYS = {
    "task",
    "instructions",
    "context_text",
    "output",
    "expected",
    "reference_facts",
    "reference_metadata",
    "notes",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_VALUE = re.compile(
    r"(?i)(?:\bBearer[ _-]+[A-Za-z0-9._-]{8,}|\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}"
    r"|(?:api[_-]?key|password|secret|credential|access[_-]?token|refresh[_-]?token)"
    r"[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{8,})"
)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_snapshot(value: Any) -> Any:
    """Remove raw content and credentials from open-ended snapshot mappings."""

    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            lowered = key.lower()
            sensitive = lowered in _RAW_KEYS or any(
                part in lowered for part in _SECRET_FRAGMENTS
            )
            if sensitive and not lowered.endswith("_sha256"):
                safe[f"{key}_sha256"] = _digest(item)
            else:
                safe[key] = _safe_snapshot(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe_snapshot(item) for item in value]
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        return f"sha256-{_digest(value)}"
    return value


def _safe_manifest(manifest: RunManifest) -> dict[str, Any]:
    payload = manifest.model_dump(mode="json")
    rubrics = []
    for rubric in payload["rubrics"]:
        pinned = rubric.get("rubric_sha256") or rubric.get("sha256")
        if not isinstance(pinned, str) or not _SHA256.fullmatch(pinned):
            pinned = _digest(rubric)
        rubrics.append(
            {
                **{
                    key: rubric[key]
                    for key in ("rubric_id", "version")
                    if key in rubric and isinstance(rubric[key], str)
                },
                "rubric_sha256": pinned,
            }
        )
    payload["rubrics"] = rubrics
    safe = _safe_snapshot(payload)
    try:
        RunManifest.model_validate(safe)
    except ValueError as error:
        raise CalibrationStorageError("redacted manifest is not loadable") from error
    return safe


def _safe_run(run: CalibrationRun) -> dict[str, Any]:
    payload = run.model_dump(mode="json")
    payload["manifest"] = _safe_manifest(run.manifest)
    safe = _safe_snapshot(payload)
    try:
        CalibrationRun.model_validate(safe)
    except ValueError as error:
        raise CalibrationStorageError("redacted run is not loadable") from error
    return safe


def _event_payload(run_id: str, event: dict) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise CalibrationStorageError("event must be a dictionary")
    unknown = set(event) - _EVENT_KEYS
    if unknown:
        raise CalibrationStorageError(f"unsafe calibration event fields: {sorted(unknown)}")
    if "kind" not in event:
        raise CalibrationStorageError("event kind is required")
    if event.get("run_id", run_id) != run_id:
        raise CalibrationStorageError("event run_id does not match run directory")
    payload = dict(event)
    payload["run_id"] = run_id
    for key in _EVENT_IDENTIFIER_KEYS:
        value = payload.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise CalibrationStorageError(f"event {key} must be a string")
            try:
                require_safe_identifier(value, field=f"event {key}")
            except ValueError as error:
                raise CalibrationStorageError(str(error)) from error
            if _SECRET_VALUE.search(value):
                raise CalibrationStorageError(f"event {key} resembles a secret")
    if isinstance(payload.get("cost_usd"), Decimal):
        payload["cost_usd"] = str(payload["cost_usd"])
    cost = payload.get("cost_usd")
    if cost is not None:
        if not isinstance(cost, str):
            raise CalibrationStorageError("event cost_usd requires Decimal or decimal string")
        try:
            parsed_cost = Decimal(str(cost))
        except InvalidOperation as error:
            raise CalibrationStorageError("event cost_usd is not numeric metadata") from error
        if not parsed_cost.is_finite() or parsed_cost < 0:
            raise CalibrationStorageError("event cost_usd must be finite and nonnegative")
        payload["cost_usd"] = str(parsed_cost)
    latency = payload.get("latency_ms")
    if latency is not None and (
        isinstance(latency, bool)
        or not isinstance(latency, (int, float))
        or not math.isfinite(latency)
        or latency < 0
    ):
        raise CalibrationStorageError("event latency_ms must be finite and nonnegative")
    attempt = payload.get("attempt_number")
    if attempt is not None and (
        isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1
    ):
        raise CalibrationStorageError("event attempt_number must be a positive integer")
    try:
        _canonical_bytes(payload)
    except (TypeError, ValueError) as error:
        raise CalibrationStorageError("event is not finite JSON metadata") from error
    return payload


class CalibrationStore:
    """One immutable directory per run, separate from production persistence."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _run_dir(self, run_id: str) -> Path:
        try:
            require_safe_identifier(run_id, field="run_id")
        except ValueError as error:
            raise CalibrationStorageError(str(error)) from error
        if _SECRET_VALUE.search(run_id):
            raise CalibrationStorageError("run_id resembles a secret")
        return self.root / run_id

    @staticmethod
    def _require_directory(path: Path, *, label: str) -> None:
        try:
            details = path.lstat()
        except OSError as error:
            raise CalibrationStorageError(f"{label} does not exist") from error
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise CalibrationStorageError(f"{label} must be a real directory")

    @staticmethod
    def _read_file(path: Path) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise CalibrationStorageError("calibration evidence must be a regular file")
                with os.fdopen(descriptor, "rb", closefd=False) as handle:
                    return handle.read()
            finally:
                os.close(descriptor)
        except OSError as error:
            raise CalibrationStorageError("cannot safely read calibration evidence") from error

    @classmethod
    def _read_verified(cls, path: Path) -> bytes:
        payload = cls._read_file(path)
        expected = cls._read_file(path.with_name(f"{path.name}.sha256")).decode("ascii").strip()
        if not _SHA256.fullmatch(expected) or hashlib.sha256(payload).hexdigest() != expected:
            raise CalibrationStorageError(f"calibration evidence checksum failed: {path.name}")
        return payload

    @staticmethod
    def _write_exclusive(path: Path, payload: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def start(self, manifest: RunManifest) -> None:
        run_dir = self._run_dir(manifest.run_id)
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._require_directory(self.root, label="calibration root")
            os.mkdir(run_dir, 0o700)
            manifest_bytes = _canonical_bytes(_safe_manifest(manifest))
            self._write_exclusive(run_dir / "manifest.json", manifest_bytes)
            self._write_exclusive(
                run_dir / "manifest.json.sha256",
                f"{hashlib.sha256(manifest_bytes).hexdigest()}\n".encode("ascii"),
            )
            self._write_exclusive(run_dir / "events.jsonl", b"")
            self._fsync_directory(run_dir)
            self._fsync_directory(self.root)
        except FileExistsError as error:
            raise CalibrationStorageError(f"run already exists: {manifest.run_id}") from error
        except OSError as error:
            raise CalibrationStorageError("could not create calibration run") from error

    def append_event(self, run_id: str, event: dict) -> None:
        run_dir = self._run_dir(run_id)
        self._require_directory(self.root, label="calibration root")
        self._require_directory(run_dir, label=f"run {run_id}")
        self._read_verified(run_dir / "manifest.json")
        payload = _canonical_bytes(_event_payload(run_id, event))
        flags = os.O_WRONLY | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(run_dir / "events.jsonl", flags)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                if os.path.lexists(run_dir / "run.json"):
                    raise CalibrationStorageError("finished calibration runs are immutable")
                written = os.write(descriptor, payload)
                if written != len(payload):
                    raise CalibrationStorageError("incomplete calibration journal append")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise CalibrationStorageError("could not append calibration event") from error

    def finish(self, run: CalibrationRun) -> None:
        run_dir = self._run_dir(run.manifest.run_id)
        self._require_directory(self.root, label="calibration root")
        self._require_directory(run_dir, label=f"run {run.manifest.run_id}")
        manifest_path = run_dir / "manifest.json"
        if run.status == "started":
            raise CalibrationStorageError("cannot finish a run with started status")
        expected = _canonical_bytes(_safe_manifest(run.manifest))
        if self._read_verified(manifest_path) != expected:
            raise CalibrationStorageError("run manifest differs from the started snapshot")
        flags = os.O_WRONLY | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(run_dir / "events.jsonl", flags)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                run_bytes = _canonical_bytes(_safe_run(run))
                self._write_exclusive(run_dir / "run.json", run_bytes)
                self._write_exclusive(
                    run_dir / "run.json.sha256",
                    f"{hashlib.sha256(run_bytes).hexdigest()}\n".encode("ascii"),
                )
                self._fsync_directory(run_dir)
            finally:
                os.close(descriptor)
        except FileExistsError as error:
            raise CalibrationStorageError("finished calibration runs are immutable") from error
        except OSError as error:
            raise CalibrationStorageError("could not finish calibration run") from error

    def save_review_output(self, run_id: str, candidate_id: str, output: str) -> str:
        """Persist an explicitly opted-in candidate output outside safe run evidence."""

        run_dir = self._run_dir(run_id)
        try:
            require_safe_identifier(candidate_id, field="candidate_id")
        except ValueError as error:
            raise CalibrationStorageError(str(error)) from error
        if _SECRET_VALUE.search(candidate_id):
            raise CalibrationStorageError("candidate_id resembles a secret")
        if not isinstance(output, str):
            raise CalibrationStorageError("review output must be a string")
        if _SECRET_VALUE.search(output):
            raise CalibrationStorageError("review output resembles a secret")
        self._require_directory(self.root, label="calibration root")
        self._require_directory(run_dir, label=f"run {run_id}")
        self._read_verified(run_dir / "manifest.json")
        output_sha256 = hashlib.sha256(output.encode("utf-8")).hexdigest()
        filename = f"{candidate_id}-{output_sha256}.json"
        relative = f"review_outputs/{filename}"
        payload = _canonical_bytes(
            {
                "schema_version": 1,
                "run_id": run_id,
                "candidate_id": candidate_id,
                "output": output,
                "output_sha256": output_sha256,
            }
        )
        flags = os.O_WRONLY | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(run_dir / "events.jsonl", flags)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                if os.path.lexists(run_dir / "run.json"):
                    raise CalibrationStorageError("finished calibration runs are immutable")
                review_dir = run_dir / "review_outputs"
                try:
                    os.mkdir(review_dir, 0o700)
                except FileExistsError:
                    self._require_directory(review_dir, label="review output directory")
                if any(review_dir.glob(f"{candidate_id}-*.json")):
                    raise CalibrationStorageError("candidate review output already exists")
                target = review_dir / filename
                self._write_exclusive(target, payload)
                self._write_exclusive(
                    target.with_name(f"{target.name}.sha256"),
                    f"{hashlib.sha256(payload).hexdigest()}\n".encode("ascii"),
                )
                self._fsync_directory(review_dir)
                self._fsync_directory(run_dir)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise CalibrationStorageError("could not save review output") from error
        return relative

    def load_review_output(self, run_id: str, candidate_id: str) -> str:
        """Load a protected output only through an explicit candidate lookup."""

        run_dir = self._run_dir(run_id)
        try:
            require_safe_identifier(candidate_id, field="candidate_id")
        except ValueError as error:
            raise CalibrationStorageError(str(error)) from error
        self._require_directory(self.root, label="calibration root")
        self._require_directory(run_dir, label=f"run {run_id}")
        self._read_verified(run_dir / "manifest.json")
        review_dir = run_dir / "review_outputs"
        self._require_directory(review_dir, label="review output directory")
        matches = tuple(review_dir.glob(f"{candidate_id}-*.json"))
        if len(matches) != 1:
            raise CalibrationStorageError("candidate review output is missing or ambiguous")
        target = matches[0]
        try:
            payload = json.loads(self._read_verified(target))
        except (ValueError, OSError) as error:
            raise CalibrationStorageError("invalid candidate review output") from error
        output = payload.get("output")
        digest = payload.get("output_sha256")
        if (
            payload.get("schema_version") != 1
            or payload.get("run_id") != run_id
            or payload.get("candidate_id") != candidate_id
            or not isinstance(output, str)
            or not isinstance(digest, str)
            or hashlib.sha256(output.encode("utf-8")).hexdigest() != digest
            or target.name != f"{candidate_id}-{digest}.json"
        ):
            raise CalibrationStorageError("candidate review output binding failed")
        return output

    def load(self, run_id: str) -> CalibrationRun:
        run_dir = self._run_dir(run_id)
        self._require_directory(self.root, label="calibration root")
        self._require_directory(run_dir, label=f"run {run_id}")
        snapshot = run_dir / "run.json"
        source = snapshot if os.path.lexists(snapshot) else run_dir / "manifest.json"
        try:
            raw = json.loads(self._read_verified(source))
            if source.name == "manifest.json":
                loaded = CalibrationRun(
                    manifest=RunManifest.model_validate(raw),
                    strategy_runs=(),
                    status="started",
                )
            else:
                loaded = CalibrationRun.model_validate(raw)
            if loaded.manifest.run_id != run_id:
                raise CalibrationStorageError("stored run_id does not match its directory")
            return loaded
        except (OSError, ValueError) as error:
            raise CalibrationStorageError(f"cannot load calibration run: {run_id}") from error
