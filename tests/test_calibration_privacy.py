from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from model_router.calibration.storage import CalibrationStorageError, CalibrationStore

from test_calibration_storage import _finished, _manifest


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PREFIXES = (
    "calibration/private/",
    "calibration/internal/",
    "calibration/sensitive/",
    "calibration/restricted/",
    "calibration/generated/",
    "calibration/runs/",
)
ARCHIVE_PRIVATE_PREFIXES = (*PRIVATE_PREFIXES, ".calibration/")


def test_persisted_snapshot_contains_hashes_but_no_raw_content_or_secrets(tmp_path: Path):
    manifest = _manifest().model_copy(
        update={
            "classifier": {
                "version": "classifier-v1",
                "api_key": "SUPER SECRET CREDENTIAL",
                "instructions": "RAW CLASSIFIER PROMPT",
            }
        }
    )
    store = CalibrationStore(tmp_path / "runs")
    store.start(manifest)
    store.finish(_finished(manifest))
    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "runs/run-1").iterdir()
    )
    for forbidden in (
        "RAW RUBRIC",
        "RAW MODEL OUTPUT",
        "SUPER SECRET CREDENTIAL",
        "RAW CLASSIFIER PROMPT",
    ):
        assert forbidden not in persisted
    assert "rubric_sha256" in persisted
    assert "api_key_sha256" in persisted
    assert "instructions_sha256" in persisted
    assert store.load("run-1").manifest.classifier["api_key_sha256"]


@pytest.mark.parametrize("key", ["task", "output", "instructions", "rubric", "error"])
def test_journal_rejects_raw_or_unbounded_fields(tmp_path: Path, key: str):
    store = CalibrationStore(tmp_path / "runs")
    store.start(_manifest())
    with pytest.raises(CalibrationStorageError, match="unsafe calibration event fields"):
        store.append_event("run-1", {"kind": "action_started", key: "raw text"})
    assert (tmp_path / "runs/run-1/events.jsonl").read_bytes() == b""


@pytest.mark.parametrize(
    "event",
    [
        {"kind": "action_started", "case_id": "sk-proj-secretvalue"},
        {"kind": "action_completed", "cost_usd": 0.1},
        {"kind": "action_completed", "cost_usd": 1},
        {"kind": "action_completed", "latency_ms": float("inf")},
    ],
)
def test_journal_rejects_secret_shaped_ids_and_lossy_numbers(tmp_path: Path, event: dict):
    store = CalibrationStore(tmp_path / "runs")
    store.start(_manifest())
    with pytest.raises(CalibrationStorageError):
        store.append_event("run-1", event)
    assert (tmp_path / "runs/run-1/events.jsonl").read_bytes() == b""


def test_build_configuration_explicitly_excludes_private_calibration_trees():
    configuration = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    docker_ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "/.calibration/" in ignored
    assert ".calibration" in docker_ignored
    for prefix in PRIVATE_PREFIXES:
        pattern = f'"/{prefix}**"'
        assert configuration.count(pattern) == 2
        assert f"/{prefix}" in ignored
        assert prefix.rstrip("/") in docker_ignored


def test_actual_source_archive_has_no_private_calibration_content(tmp_path: Path):
    uv = os.environ.get("MODEL_ROUTER_UV") or shutil.which("uv")
    local_uv = Path("/private/tmp/openai-model-router-uv/bin/uv")
    if uv is None and local_uv.is_file():
        uv = str(local_uv)
    if uv is None:
        pytest.skip("uv executable unavailable for actual archive inspection")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    for name in ("pyproject.toml", "hatch_build.py", "README.md", "uv.lock"):
        shutil.copy2(ROOT / name, checkout / name)
    for name in ("src", "migrations", "dashboard/dist"):
        shutil.copytree(ROOT / name, checkout / name)
    sentinel = "PRIVATE_CALIBRATION_SENTINEL_MUST_NOT_SHIP"
    for prefix in ARCHIVE_PRIVATE_PREFIXES:
        directory = checkout / prefix
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "private-case.jsonl").write_text(sentinel, encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    environment = os.environ.copy()
    environment.setdefault("UV_CACHE_DIR", "/private/tmp/openai-model-router-uv-cache")
    subprocess.run(
        [uv, "build", "--offline", "--out-dir", str(artifacts), str(checkout)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    source_archive = next(artifacts.glob("*.tar.gz"))
    with tarfile.open(source_archive, "r:gz") as built:
        members = ["/".join(name.split("/")[1:]) for name in built.getnames()]
        payloads = [
            built.extractfile(member).read()
            for member in built.getmembers()
            if member.isfile()
        ]
    assert not any(
        member.startswith(prefix)
        for member in members
        for prefix in ARCHIVE_PRIVATE_PREFIXES
    )
    assert all(sentinel.encode() not in payload for payload in payloads)

    wheel = next(artifacts.glob("*.whl"))
    with zipfile.ZipFile(wheel) as built:
        members = built.namelist()
        payloads = [built.read(member) for member in members]
    assert not any(
        member.startswith(prefix)
        for member in members
        for prefix in ARCHIVE_PRIVATE_PREFIXES
    )
    assert all(sentinel.encode() not in payload for payload in payloads)
