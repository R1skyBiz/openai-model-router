from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from model_router.calibration.contracts import (
    BlindCandidate,
    CalibrationCase,
    CallEvidence,
    SemanticScore,
)
from model_router.calibration.corpus import (
    CorpusError,
    canonical_case_input,
    canonical_case_input_sha256,
    canonical_comparison_sha256,
    load_corpus,
    stable_id,
)
from model_router.calibration.grading import BlindGrader


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "calibration/sample/corpus-v1.jsonl"


def _case(**updates) -> CalibrationCase:
    payload = {
        "case_id": "case-1",
        "corpus_version": "test-v1",
        "task_family_hint": "annotation-only",
        "source_kind": "synthetic_control",
        "task": "Return the word blue.",
        "instructions": "Return one lowercase word.",
        "context_text": "The selected color is blue.",
        "requirements": ["text_input", "text_output"],
        "consequence": "low",
        "context": {"input_tokens": 20, "expected_output_tokens": 3},
        "deadline_ms": 30000,
        "output_contract": {"format": "text", "constraints": ["one_word"]},
        "tool_policy": {"available": [], "side_effects": False},
        "grading": {"deterministic": [{"kind": "exact", "expected": "blue"}]},
        "privacy": "public",
        "tags": ["secret-eval-tag"],
        "notes": "grader-only-note",
        "reference_metadata": {"answer_origin": "author"},
    }
    payload.update(updates)
    return CalibrationCase.model_validate(payload)


def _write_corpus(path: Path, cases: list[CalibrationCase], **manifest_updates) -> None:
    content = "".join(case.model_dump_json() + "\n" for case in cases).encode()
    path.write_bytes(content)
    manifest = {
        "schema_version": 1,
        "corpus_version": "test-v1",
        "corpus_sha256": hashlib.sha256(content).hexdigest(),
        "case_count": len(cases),
        "privacy": "public",
        "description": "test",
    }
    manifest.update(manifest_updates)
    path.with_suffix(".manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_committed_sample_is_pinned_public_and_has_24_distinct_cases():
    cases, manifest = load_corpus(SAMPLE)
    assert manifest.case_count == len(cases) == 24
    assert set(manifest.case_hashes) == {case.case_id for case in cases}
    assert manifest.privacy == "public"
    assert {case.source_kind for case in cases} == {
        "synthetic_control",
        "authored_realistic",
    }
    assert all(case.privacy == "public" for case in cases)
    assert all(case.consequence == "low" for case in cases)
    assert all(
        set(case.requirements) <= {"text_input", "text_output", "structured_outputs"}
        for case in cases
    )
    assert any(case.grading.rubric is not None for case in cases)
    assert sum(not case.grading.deterministic for case in cases) == 2


def test_public_mock_outputs_cover_and_pass_every_sample_case():
    cases, _ = load_corpus(SAMPLE)
    fixture = json.loads((SAMPLE.parent / "mock-v1.json").read_text(encoding="utf-8"))
    assert set(fixture["outputs"]) == {case.case_id for case in cases}
    class PassingEvaluator:
        def evaluate(self, candidate, rubric):
            return SemanticScore(
                rubric_id=rubric.rubric_id,
                rubric_version=rubric.version,
                score="0.95",
                status="scored",
                calls=(
                    CallEvidence(
                        call_id=stable_id("judge", candidate.candidate_id),
                        purpose="judge",
                        cost_usd="0",
                        status="completed",
                    ),
                ),
            )

    grader = BlindGrader(evaluator=PassingEvaluator())
    for case in cases:
        grade = grader.grade(
            BlindCandidate(
                candidate_id=stable_id("candidate", case.case_id),
                task=case.task,
                instructions=case.instructions,
                context_text=case.context_text,
                output=fixture["outputs"][case.case_id],
                output_contract=case.output_contract,
                grading=case.grading,
            )
        )
        assert grade.disposition == "PASS", (case.case_id, grade.evidence_codes)


def test_sample_json_contracts_are_strict_provider_compatible():
    cases, _ = load_corpus(SAMPLE)

    def strict(schema: Mapping) -> None:
        if schema.get("type") == "object":
            assert schema.get("additionalProperties") is False
            properties = schema.get("properties")
            assert isinstance(properties, Mapping) and properties
            assert set(schema.get("required", ())) == set(properties)
            for child in properties.values():
                strict(child)
        if schema.get("type") == "array":
            assert "items" in schema
            strict(schema["items"])

    for case in cases:
        schema = case.output_contract.json_schema
        if schema is not None:
            strict(dict(schema))


def test_canonical_generation_input_cannot_leak_annotations():
    case = _case()
    value = canonical_case_input(case)
    parsed = json.loads(value)
    assert set(parsed) == {"task", "instructions", "context", "output_contract"}
    for forbidden in (
        "annotation-only",
        "secret-eval-tag",
        "grader-only-note",
        "answer_origin",
        "blue\"}]",  # serialized deterministic expected value
    ):
        assert forbidden not in value
    changed_annotations = case.model_copy(
        update={"task_family_hint": "different", "tags": ("other",), "notes": "other"}
    )
    assert canonical_case_input_sha256(case) == canonical_case_input_sha256(changed_annotations)


def test_comparison_hash_covers_fairness_envelope_but_not_annotations():
    case = _case()
    assert canonical_comparison_sha256(case) != canonical_comparison_sha256(
        case.model_copy(update={"deadline_ms": 31000})
    )
    assert canonical_comparison_sha256(case) == canonical_comparison_sha256(
        case.model_copy(update={"notes": "changed", "task_family_hint": "changed"})
    )


def test_loader_rejects_tampering_duplicates_and_privacy_mismatch(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    _write_corpus(path, [_case()])
    assert load_corpus(path)[0][0].case_id == "case-1"

    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(CorpusError, match="SHA-256"):
        load_corpus(path)

    duplicate = _case(case_id="case-2")
    _write_corpus(path, [_case(), duplicate])
    with pytest.raises(CorpusError, match="duplicate canonical input"):
        load_corpus(path)

    _write_corpus(path, [_case(privacy="internal")], privacy="public")
    with pytest.raises(CorpusError, match="most restrictive"):
        load_corpus(path)

    _write_corpus(path, [_case()], case_hashes={"case-1": "f" * 64})
    with pytest.raises(CorpusError, match="case_hashes"):
        load_corpus(path)


def test_loader_rejects_unsafe_and_duplicate_ids(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    _write_corpus(path, [_case(case_id="../escape")])
    with pytest.raises(CorpusError, match="portable identifier"):
        load_corpus(path)

    _write_corpus(path, [_case(), _case(instructions="Different.")])
    with pytest.raises(CorpusError, match="duplicate case_id"):
        load_corpus(path)
    assert stable_id("candidate", "run-1", "case-1") == stable_id(
        "candidate", "run-1", "case-1"
    )


def test_loader_accepts_missing_family_hint_and_rejects_conflicting_rubric_version(
    tmp_path: Path,
):
    path = tmp_path / "cases.jsonl"
    rubric = {
        "rubric_id": "quality",
        "version": "v1",
        "instructions": "Score correctness.",
        "threshold": "0.8",
    }
    first = _case(
        task_family_hint=None,
        grading={"rubric": rubric},
    )
    second = _case(
        case_id="case-2",
        task="Return the word green.",
        grading={"rubric": {**rubric, "threshold": "0.9"}},
    )
    _write_corpus(path, [first, second])
    with pytest.raises(CorpusError, match="conflicting rubric identity"):
        load_corpus(path)
