from __future__ import annotations

import hashlib
import json
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from model_router.calibration.contracts import (
    CalibrationRun,
    CorpusManifest,
    ExperimentConfig,
    Grade,
    RunManifest,
    Strategy,
    StrategyRun,
)
from model_router.calibration.storage import CalibrationStorageError, CalibrationStore


def _manifest(run_id: str = "run-1") -> RunManifest:
    return RunManifest(
        run_id=run_id,
        created_at=datetime(2026, 9, 7, tzinfo=UTC),
        corpus=CorpusManifest(
            corpus_version="sample-v1",
            corpus_sha256="a" * 64,
            case_count=1,
            privacy="public",
        ),
        policy_version="policy-v1",
        policy_sha256="b" * 64,
        model_catalog={"version": "models-v1", "models": ["gpt-test"]},
        pricing_snapshot={"version": "prices-v1", "gpt-test": {"input": "0.1"}},
        classifier={"version": "classifier-v1", "sha256": "c" * 64},
        rubrics=({"rubric_id": "quality", "version": "v1", "instructions": "RAW RUBRIC"},),
        config=ExperimentConfig(
            version="experiment-v1",
            strategies=(
                Strategy(name="router", kind="router"),
                Strategy(name="terra", kind="fixed", model="gpt-test", effort="medium"),
            ),
            aggregate_cap_usd="1",
            max_input_tokens=1000,
            max_output_tokens=100,
        ),
        offline=True,
        strategy_order={"case-1": ("router", "terra")},
    )


def _finished(manifest: RunManifest) -> CalibrationRun:
    strategy = manifest.config.strategies[0]
    strategy_run = StrategyRun(
        strategy_run_id="strategy-1",
        case_id="case-1",
        strategy=strategy,
        input_sha256="d" * 64,
        validation_signature="v0-test",
        policy_version="policy-v1",
        execution_status="completed",
        complete=True,
        output="RAW MODEL OUTPUT",
        source_kind="synthetic_control",
        consequence="low",
    )
    return CalibrationRun(
        manifest=manifest,
        strategy_runs=(strategy_run,),
        status="completed",
    )


def test_store_round_trips_started_and_finished_typed_runs(tmp_path: Path):
    store = CalibrationStore(tmp_path / "runs")
    manifest = _manifest()
    store.start(manifest)
    started = store.load("run-1")
    assert isinstance(started, CalibrationRun)
    assert started.status == "started"
    assert started.manifest.rubrics[0]["rubric_id"] == "quality"
    assert "rubric_sha256" in started.manifest.rubrics[0]

    store.append_event("run-1", {"kind": "action_started", "call_id": "call-1", "status": "started"})
    store.finish(_finished(manifest))
    loaded = store.load("run-1")
    assert isinstance(loaded, CalibrationRun)
    assert loaded.status == "completed"
    assert loaded.strategy_runs[0].output is None
    with pytest.raises(CalibrationStorageError, match="immutable"):
        store.append_event("run-1", {"kind": "late_event"})
    with pytest.raises(CalibrationStorageError, match="immutable"):
        store.finish(_finished(manifest))


def test_loaded_redacted_manifest_can_be_finished_without_rehashing_rubric(tmp_path: Path):
    store = CalibrationStore(tmp_path / "runs")
    manifest = _manifest().model_copy(
        update={"rubrics": ({"rubric_id": "quality", "version": "v1", "sha256": "e" * 64},)}
    )
    store.start(manifest)
    started = store.load("run-1")
    assert started.manifest.rubrics[0]["rubric_sha256"] == "e" * 64
    store.finish(started.model_copy(update={"status": "stopped", "stop_reason": "operator_stop"}))
    assert store.load("run-1").manifest.rubrics[0]["rubric_sha256"] == "e" * 64


def test_run_directories_are_exclusive_and_identifiers_cannot_escape(tmp_path: Path):
    store = CalibrationStore(tmp_path / "runs")
    manifest = _manifest()
    store.start(manifest)
    with pytest.raises(CalibrationStorageError, match="already exists"):
        store.start(manifest)
    with pytest.raises(CalibrationStorageError, match="portable identifier"):
        store.load("../outside")


def test_journal_retains_started_and_uncertain_safe_metadata(tmp_path: Path):
    store = CalibrationStore(tmp_path / "runs")
    store.start(_manifest())
    store.append_event(
        "run-1",
        {
            "kind": "action_started",
            "strategy_run_id": "strategy-1",
            "call_id": "call-1",
            "purpose": "generation",
            "status": "started",
        },
    )
    store.append_event(
        "run-1",
        {
            "kind": "action_completed",
            "strategy_run_id": "strategy-1",
            "call_id": "call-1",
            "purpose": "generation",
            "status": "unknown",
            "failure_type": "provider_failure",
        },
    )
    lines = (tmp_path / "runs/run-1/events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert '"status":"started"' in lines[0]
    assert '"status":"unknown"' in lines[1]


def test_manifest_and_final_snapshot_tampering_fail_closed(tmp_path: Path):
    store = CalibrationStore(tmp_path / "runs")
    store.start(_manifest())
    manifest_path = tmp_path / "runs/run-1/manifest.json"
    manifest_path.write_bytes(manifest_path.read_bytes().replace(b'"offline":true', b'"offline":false'))
    with pytest.raises(CalibrationStorageError, match="checksum failed"):
        store.load("run-1")

    second = CalibrationStore(tmp_path / "other")
    second.start(_manifest("run-2"))
    second.finish(_finished(_manifest("run-2")))
    run_path = tmp_path / "other/run-2/run.json"
    run_path.write_bytes(run_path.read_bytes() + b" ")
    with pytest.raises(CalibrationStorageError, match="checksum failed"):
        second.load("run-2")


def test_root_and_run_directory_symlinks_are_rejected(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(target, target_is_directory=True)
    with pytest.raises(CalibrationStorageError, match="real directory"):
        CalibrationStore(linked_root).start(_manifest())

    root = tmp_path / "runs"
    root.mkdir()
    (root / "run-1").symlink_to(target, target_is_directory=True)
    with pytest.raises(CalibrationStorageError, match="real directory"):
        CalibrationStore(root).load("run-1")


def test_load_rejects_validly_checksummed_manifest_in_wrong_directory(tmp_path: Path):
    store = CalibrationStore(tmp_path / "runs")
    store.start(_manifest())
    path = tmp_path / "runs/run-1/manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["run_id"] = "different-run"
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    path.write_bytes(encoded)
    path.with_name("manifest.json.sha256").write_text(
        hashlib.sha256(encoded).hexdigest() + "\n", encoding="ascii"
    )
    with pytest.raises(CalibrationStorageError, match="run_id"):
        store.load("run-1")


def test_append_and_finish_are_serialized_without_post_finish_events(tmp_path: Path):
    store = CalibrationStore(tmp_path / "runs")
    manifest = _manifest()
    store.start(manifest)

    def append(index: int) -> str:
        try:
            store.append_event(
                "run-1",
                {"kind": "action_started", "call_id": f"call-{index}", "status": "started"},
            )
            return "appended"
        except CalibrationStorageError as error:
            assert "immutable" in str(error)
            return "finished"

    with ThreadPoolExecutor(max_workers=9) as pool:
        futures = [pool.submit(append, index) for index in range(20)]
        finish = pool.submit(store.finish, _finished(manifest))
        outcomes = [future.result() for future in futures]
        finish.result()
    assert set(outcomes) <= {"appended", "finished"}
    lines = (tmp_path / "runs/run-1/events.jsonl").read_text().splitlines()
    assert len(lines) == outcomes.count("appended")
    assert all(json.loads(line)["kind"] == "action_started" for line in lines)


def test_review_outputs_require_explicit_save_and_bind_candidate_and_digest(tmp_path: Path):
    store = CalibrationStore(tmp_path / "runs")
    manifest = _manifest()
    store.start(manifest)
    assert not (tmp_path / "runs/run-1/review_outputs").exists()

    reference = store.save_review_output("run-1", "candidate-1", "answer needing review")
    digest = hashlib.sha256(b"answer needing review").hexdigest()
    assert reference == f"review_outputs/candidate-1-{digest}.json"
    target = tmp_path / "runs/run-1" / reference
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert store.load_review_output("run-1", "candidate-1") == "answer needing review"
    with pytest.raises(CalibrationStorageError, match="already exists"):
        store.save_review_output("run-1", "candidate-1", "replacement")

    finished = _finished(manifest)
    strategy_run = finished.strategy_runs[0].model_copy(
        update={
            "grade": Grade(
                candidate_id="candidate-1",
                disposition="NEEDS_REVIEW",
                human_review_needed=True,
                output_reference=reference,
            )
        }
    )
    store.finish(finished.model_copy(update={"strategy_runs": (strategy_run,)}))
    loaded = store.load("run-1")
    assert loaded.strategy_runs[0].grade.output_reference == reference
    assert store.load_review_output("run-1", "candidate-1") == "answer needing review"
    with pytest.raises(CalibrationStorageError, match="immutable"):
        store.save_review_output("run-1", "candidate-2", "late output")


def test_review_output_rejects_secrets_and_tampering(tmp_path: Path):
    store = CalibrationStore(tmp_path / "runs")
    store.start(_manifest())
    with pytest.raises(CalibrationStorageError, match="resembles a secret"):
        store.save_review_output("run-1", "candidate-1", "api_key=abcdefghijk")
    assert not (tmp_path / "runs/run-1/review_outputs").exists()

    reference = store.save_review_output("run-1", "candidate-1", "safe disputed output")
    target = tmp_path / "runs/run-1" / reference
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(CalibrationStorageError, match="checksum failed"):
        store.load_review_output("run-1", "candidate-1")
