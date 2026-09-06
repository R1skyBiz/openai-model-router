"""Validate, audit and grade offline JSONL. No router or provider imports."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

import yaml

# Also support `python evals/run_local.py` from any working directory.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.grader import grade
from evals.schema import Case, Observation

CASES_DIR = ROOT / "evals/cases"


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_nonfinite(value):
    raise ValueError(f"nonfinite JSON number: {value}")


def read_jsonl(path, record_type):
    rows = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip():
            try:
                raw = json.loads(line, object_pairs_hook=unique_object,
                                 parse_constant=reject_nonfinite)
                rows.append(record_type.model_validate(raw))
            except (ValueError, TypeError) as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
    return rows


def load_contract():
    manifest = json.loads((ROOT / "evals/fixtures/manifest.json").read_text())
    for name, digest in manifest["sha256"].items():
        if sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"pinned contract changed: {name}; review corpus before repinning")
    catalog = yaml.safe_load((ROOT / "config/models.yaml").read_text())["models"]
    # Only vocabulary/ranges for validating case shape, never candidates/floors.
    vocabulary = json.loads((ROOT / "evals/fixtures/vocabulary.json").read_text())
    return manifest, catalog, vocabulary


def load_cases(directory=CASES_DIR):
    _, catalog, vocab = load_contract()
    cases = [row for path in sorted(directory.glob("*.jsonl")) for row in read_jsonl(path, Case)]
    seen, signatures = set(), set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"duplicate case ID: {case.id}")
        seen.add(case.id)
        signature = json.dumps([case.request.model_dump(),
                                case.classification.model_dump() if case.classification else None,
                                case.environment.model_dump(),
                                case.scenario.model_dump() if case.scenario else None], sort_keys=True)
        if signature in signatures:
            raise ValueError(f"duplicate behavioral input: {case.id}")
        signatures.add(signature)
        if case.environment.snapshot != "offline-v1":
            raise ValueError(f"unknown synthetic snapshot: {case.id}")
        if not set(case.environment.overrides) <= {"health", "budget", "validation", "pricing", "latency", "telemetry"}:
            raise ValueError(f"unknown snapshot section: {case.id}")
        if case.environment.application_overlay is not None and not case.environment.application_overlay_version:
            raise ValueError(f"unversioned overlay: {case.id}")
        if case.classification:
            cl = case.classification
            if cl.task_family not in vocab["families"]:
                raise ValueError(f"unknown task family: {case.id}")
            if set(cl.components) != set(vocab["components"]):
                raise ValueError(f"missing/unknown components: {case.id}")
            for name, value in cl.components.items():
                if not 0 <= value <= vocab["components"][name]:
                    raise ValueError(f"component out of bounds: {case.id}/{name}")
            if not set(cl.flags) <= set(vocab["flags"]):
                raise ValueError(f"unknown flags: {case.id}")
        exp = case.expected
        if not set(exp.required_rationale_codes + exp.forbidden_rationale_codes) <= set(vocab["rationale_codes"]):
            raise ValueError(f"unknown rationale: {case.id}")
        if not set(exp.forbidden_models) <= set(catalog):
            raise ValueError(f"unknown forbidden model: {case.id}")
        trace_pairs = [step.route for step in exp.expected_recovery if step.route]
        if case.scenario:
            trace_pairs.append(case.scenario.initial_route)
            if case.scenario.initial_route not in exp.acceptable_model_efforts:
                raise ValueError(f"initial script route outside envelope: {case.id}")
        for pair in trace_pairs:
            if pair.model not in catalog or pair.effort not in catalog[pair.model]["reasoning_efforts"]:
                raise ValueError(f"unsupported scripted route: {case.id}")
        for pair in exp.acceptable_model_efforts:
            model = catalog.get(pair.model)
            if model is None or pair.effort not in model["reasoning_efforts"]:
                raise ValueError(f"unsupported expected pair: {case.id}")
            rank = model["tier_rank"]
            if (exp.minimum_tier is not None and rank < exp.minimum_tier or
                    exp.maximum_tier is not None and rank > exp.maximum_tier):
                raise ValueError(f"pair contradicts tier envelope: {case.id}")
            if not all(model["capabilities"].get(c) is True for c in case.request.requirements):
                raise ValueError(f"incapable expected model: {case.id}")
            ctx = case.request.context
            if (ctx.expected_output_tokens > model["max_output_tokens"] or
                    ctx.input_tokens + ctx.expected_output_tokens > model["context_window_tokens"]):
                raise ValueError(f"infeasible expected context: {case.id}")
        if case.category == "classification":
            if not set(exp.acceptable_task_families + exp.forbidden_task_families) <= set(vocab["families"]):
                raise ValueError(f"unknown expected family: {case.id}")
            if set(exp.component_envelopes) != set(vocab["components"]):
                raise ValueError(f"classification must envelope all components: {case.id}")
            if not set(exp.flags) <= set(vocab["flags"]):
                raise ValueError(f"unknown expected flag: {case.id}")
            for name, (lo, hi) in exp.component_envelopes.items():
                if not 0 <= lo <= hi <= vocab["components"][name]:
                    raise ValueError(f"component envelope out of bounds: {case.id}")
    return cases


def validate_cases():
    return len(load_cases())


def coverage(cases):
    def counts(values):
        return dict(sorted(Counter(values).items()))

    # Reporting bins only: intentionally not the configured routing prior bands.
    def band(case):
        if case.classification is None:
            return "classification seed"
        total = sum(case.classification.components.values())
        return f"{min(total // 20, 4) * 20:02d}–{min(total // 20, 4) * 20 + 19 if total < 80 else 100:02d}"

    return {
        "total": len(cases),
        "category": counts(c.category for c in cases),
        "task_family_primary": counts(c.classification.task_family if c.classification
                                      else c.expected.acceptable_task_families[0] for c in cases),
        "task_family_supplied": counts(c.classification.task_family for c in cases if c.classification),
        "classification_family_envelopes": counts(f for c in cases for f in c.expected.acceptable_task_families),
        "complexity_band": counts(band(c) for c in cases),
        "model_envelope": counts("/".join(sorted({p.model for p in c.expected.acceptable_model_efforts}))
                                 or "no route" for c in cases),
        "validation_profile": counts(c.expected.validation_profile or "not applicable" for c in cases),
        "failure_type": counts(c.expected.expected_failure or
                               "/".join(c.expected.acceptable_failure_types) or "none" for c in cases),
        "recovery_failure_type": counts(s.failure or "success" for c in cases for s in c.expected.expected_recovery),
        "health_scenario": counts(c.environment.health_scenario for c in cases),
        "budget_scenario": counts(c.environment.budget_scenario for c in cases),
        "must_not_use_astra": sum("astra" in c.expected.forbidden_models for c in cases),
        "boundaries": sorted({sum(c.classification.components.values()) for c in cases
                              if c.classification and "boundary" in c.tags}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, help="supplied observation JSONL to grade")
    parser.add_argument("--allow-subset", action="store_true", help="explicitly permit a fixture subset")
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args()
    try:
        cases = load_cases()
        print(f"Validated {len(cases)} cases.")
        if args.coverage:
            print(json.dumps(coverage(cases), indent=2))
        if args.results:
            results = read_jsonl(args.results, Observation)
            ids = [r.case_id for r in results]
            if not ids or len(ids) != len(set(ids)):
                raise ValueError("results must be nonempty with unique case IDs")
            index = {c.id: c for c in cases}
            if set(ids) - index.keys():
                raise ValueError("results contain unknown case IDs")
            if not args.allow_subset and set(ids) != index.keys():
                raise ValueError("incomplete result set; use --allow-subset only for fixture checks")
            manifest, catalog, vocabulary = load_contract()
            failed = 0
            for result in results:
                errors = grade(index[result.case_id], result, catalog, manifest["policy_version"], vocabulary)
                if errors:
                    failed += 1
                    print(f"FAIL {result.case_id}: {'; '.join(errors)}")
            print(f"Graded {len(results)} observations: {len(results) - failed} passed, {failed} failed.")
            return int(bool(failed))
        return 0
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
