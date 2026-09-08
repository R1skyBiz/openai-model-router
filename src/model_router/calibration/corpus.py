"""Versioned calibration corpus loading and canonical generation input."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import ValidationError

from model_router.calibration.contracts import CalibrationCase, CorpusManifest


class CorpusError(ValueError):
    """The corpus or its manifest is malformed or internally inconsistent."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PRIVACY_ORDER = {"public": 0, "internal": 1, "sensitive": 2, "restricted": 3}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def require_safe_identifier(value: str, *, field: str = "identifier") -> str:
    """Reject identifiers that could escape a persistence namespace."""

    if not _IDENTIFIER.fullmatch(value):
        raise CorpusError(f"{field} must be a portable identifier")
    return value


def canonical_case_input(case: CalibrationCase) -> str:
    """Return the sole generation payload, excluding every evaluation annotation.

    Requirements, consequence, token bounds, tool policy, and deadline are execution
    envelopes supplied independently to every strategy. They are deliberately absent
    here, as are source, family, privacy, tags, notes, references, and grading data.
    """

    return _canonical_json(
        {
            "context": case.context_text,
            "instructions": case.instructions,
            "output_contract": case.output_contract.model_dump(mode="json"),
            "task": case.task,
        }
    )


def canonical_case_input_sha256(case: CalibrationCase) -> str:
    return hashlib.sha256(canonical_case_input(case).encode("utf-8")).hexdigest()


def canonical_comparison_sha256(case: CalibrationCase) -> str:
    """Hash the prompt and every fairness envelope shared by strategies."""

    payload = {
        "canonical_input": json.loads(canonical_case_input(case)),
        "consequence": case.consequence,
        "context_bounds": case.context.model_dump(mode="json"),
        "deadline_ms": case.deadline_ms,
        "requirements": case.requirements,
        "tool_policy": case.tool_policy.model_dump(mode="json"),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def case_content_sha256(case: CalibrationCase) -> str:
    """Hash the full case for provenance without exposing its content."""

    payload = case.model_dump(mode="json")
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: str) -> str:
    """Build a portable opaque ID from non-secret provenance values."""

    require_safe_identifier(prefix, field="prefix")
    if not parts:
        raise CorpusError("stable_id requires at least one part")
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def manifest_path(corpus_path: str | Path) -> Path:
    return Path(corpus_path).with_suffix(".manifest.json")


def load_corpus(path: str | Path) -> tuple[tuple[CalibrationCase, ...], CorpusManifest]:
    """Load and verify a JSONL corpus against its adjacent byte-level manifest."""

    corpus_path = Path(path)
    try:
        corpus_bytes = corpus_path.read_bytes()
    except OSError as error:
        raise CorpusError(f"cannot read corpus: {corpus_path}") from error
    try:
        corpus_text = corpus_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CorpusError("corpus must be UTF-8") from error

    adjacent = manifest_path(corpus_path)
    try:
        raw_manifest = json.loads(adjacent.read_text(encoding="utf-8"))
        manifest = CorpusManifest.model_validate(raw_manifest)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise CorpusError(f"invalid corpus manifest: {adjacent}") from error

    expected_hash = hashlib.sha256(corpus_bytes).hexdigest()
    if manifest.corpus_sha256 != expected_hash:
        raise CorpusError("corpus SHA-256 does not match manifest")
    require_safe_identifier(manifest.corpus_version, field="corpus_version")

    cases: list[CalibrationCase] = []
    ids: set[str] = set()
    inputs: dict[str, str] = {}
    rubric_cores: dict[tuple[str, str], str] = {}
    for line_number, line in enumerate(corpus_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = CalibrationCase.model_validate_json(line)
        except (ValueError, ValidationError) as error:
            raise CorpusError(f"invalid case at line {line_number}") from error
        require_safe_identifier(case.case_id, field=f"case_id at line {line_number}")
        if case.case_id in ids:
            raise CorpusError(f"duplicate case_id: {case.case_id}")
        ids.add(case.case_id)
        if case.corpus_version != manifest.corpus_version:
            raise CorpusError(f"case {case.case_id} has the wrong corpus_version")
        input_hash = canonical_case_input_sha256(case)
        if input_hash in inputs:
            raise CorpusError(
                f"duplicate canonical input: {inputs[input_hash]} and {case.case_id}"
            )
        inputs[input_hash] = case.case_id
        rubric = case.grading.rubric
        if rubric is not None:
            core = rubric.model_dump(mode="json")
            core.pop("reference_facts", None)
            core_hash = hashlib.sha256(_canonical_json(core).encode("utf-8")).hexdigest()
            identity = (rubric.rubric_id, rubric.version)
            existing = rubric_cores.setdefault(identity, core_hash)
            if existing != core_hash:
                raise CorpusError(
                    f"conflicting rubric identity: {rubric.rubric_id}/{rubric.version}"
                )
        cases.append(case)

    if not cases:
        raise CorpusError("corpus contains no cases")
    if len(cases) != manifest.case_count:
        raise CorpusError("case_count does not match manifest")
    max_privacy = max((case.privacy for case in cases), key=_PRIVACY_ORDER.__getitem__)
    if manifest.privacy != max_privacy:
        raise CorpusError("manifest privacy must equal the most restrictive case")
    computed_hashes = {case.case_id: case_content_sha256(case) for case in cases}
    if manifest.case_hashes and dict(manifest.case_hashes) != computed_hashes:
        raise CorpusError("case_hashes do not match the loaded cases")
    if not manifest.case_hashes:
        manifest = manifest.model_copy(update={"case_hashes": computed_hashes})
    return tuple(cases), manifest
