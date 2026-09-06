"""Run all authored classification seeds through a mock or explicitly gated live classifier."""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for search_path in (ROOT, ROOT / "src"):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from evals.grader import grade
from evals.live_support import (
    LiveEvalError, check_input_bound, live_cost_bound, load_live_settings,
    require_live_access, usage_cost,
)
from evals.phase2_adapter import DATA, load_mock_outputs, observe
from evals.run_local import load_cases, load_contract
from model_router.classification import (
    MockClassifier, OpenAIClassifier, build_output_type, load_classifier_config,
)
from model_router.policy.loader import load_bundle


def _counts(values) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _build_classifier(*, live: bool, bundle, cases):
    if not live:
        config = load_classifier_config(ROOT / "config/classifier.yaml", bundle)
        return MockClassifier(load_mock_outputs(), bundle, config), config, None, None

    settings = load_live_settings(os.environ.get("OPENAI_LIVE_EVAL_CONFIG", str(ROOT / "config/live-eval.yaml")))
    require_live_access(settings)
    config = load_classifier_config(DATA / "live-classifier.yaml", bundle)
    bound = live_cost_bound(
        settings, bundle, config.model_alias, config.max_output_tokens, len(cases),
    )
    output_schema = build_output_type(bundle).model_json_schema()
    for case in cases:
        serialized = json.dumps(
            {"instructions": config.prompt_text, "input": case.request.input,
             "output_schema": output_schema}, sort_keys=True,
        )
        check_input_bound(settings, serialized)
    from model_router.execution.openai_provider import OpenAIProvider
    classifier = OpenAIClassifier(OpenAIProvider(bundle), bundle, config)
    return classifier, config, settings, bound


def _coverage(observations, cases, failures, *, live: bool) -> dict:
    classifications = [row.classification for row in observations if row.classification]
    components = sorted({name for row in classifications for name in row.components})
    flags = sorted({name for row in classifications for name in row.flags})
    ambiguous = [case.id for case in cases if len(case.expected.acceptable_task_families) > 1]
    observed = {row.case_id: row for row in observations}
    dimensions = {
        "family_envelope": ("classification family", "forbidden family"),
        "component_envelope": ("classification component",),
        "flags": ("classification flag",),
    }
    passes = {}
    for dimension, prefixes in dimensions.items():
        passed = sum(case.id in observed and observed[case.id].classification is not None
                     and not any(error.startswith(prefixes) for error in failures.get(case.id, ()))
                     for case in cases)
        passes[dimension] = {"passed": passed, "failed": len(cases) - passed}
    provenance_passed = sum(row.classification is not None and bool(row.classification.provenance)
        and all(row.facts.get(field) for field in (
            "classifier_version", "prompt_version", "classifier_schema_version", "configuration_hash"))
        for row in observations)
    passes["confidence_and_provenance_schema"] = {
        "passed": provenance_passed, "failed": len(cases) - provenance_passed}
    return {
        "dimension_passes": passes,
        "family_counts": _counts(row.task_family for row in classifications),
        "family_envelope_counts": _counts(
            family for case in cases for family in case.expected.acceptable_task_families
        ),
        "envelope_counts": {
            "passed": len(cases) - len(failures), "failed": len(failures),
        },
        "component_counts": {
            name: _counts(str(row.components[name]) for row in classifications)
            for name in components
        },
        "flag_counts": {
            name: {
                "true": sum(row.flags.get(name) is True for row in classifications),
                "false": sum(row.flags.get(name) is False for row in classifications),
            }
            for name in flags
        },
        "provenance_counts": _counts(row.provenance for row in classifications),
        "ambiguities": {
            "authored_multi_family_envelope_count": len(ambiguous),
            "authored_multi_family_envelope_cases": ambiguous,
            "classification_source": "live" if live else "deterministic_mock",
            "note": "Authored family envelopes are review allowances, not measured live uncertainty.",
        },
    }


def run(*, live: bool = False, classifier=None, bundle=None, cases=None):
    all_cases = load_cases() if cases is None else list(cases)
    cases = [case for case in all_cases if case.category == "classification"]
    manifest, catalog, vocabulary = load_contract()
    bundle = bundle or load_bundle(ROOT / "config")
    config = settings = preflight_bound = None
    if classifier is None:
        classifier, config, settings, preflight_bound = _build_classifier(
            live=live, bundle=bundle, cases=cases,
        )

    observations, classified_outcomes, failures = [], [], {}
    for case in cases:
        try:
            observation, outcome = observe(case, classifier, manifest["policy_version"])
            observations.append(observation)
            classified_outcomes.append((case, outcome))
            errors = grade(case, observation, catalog, manifest["policy_version"], vocabulary)
        except (ValueError, TypeError, KeyError):
            errors = ["adapter/classifier contract error"]
        if errors:
            failures[case.id] = errors

    live_cost = None
    if live and settings is not None and config is not None:
        model = bundle.catalog["models"][config.model_alias]
        costs = []
        for case, outcome in classified_outcomes:
            provider_result = getattr(outcome, "provider_result", None)
            cost = usage_cost(provider_result.usage, model) if provider_result is not None else None
            if cost is None:
                failures.setdefault(case.id, []).append("live usage cost unavailable")
            else:
                costs.append(cost)
        observed = sum(costs, Decimal("0"))
        if settings.max_total_cost_usd is not None and observed > settings.max_total_cost_usd:
            raise LiveEvalError("observed classifier eval cost exceeded total cost cap")
        live_cost = {
            "preflight_bound_usd": str(preflight_bound),
            "observed_usd": str(observed) if len(costs) == len(cases) else None,
            "known_subtotal_usd": str(observed),
            "complete": len(costs) == len(cases),
        }

    report = {
        "mode": "live" if live else "mock",
        "total_corpus": len(all_cases),
        "classification_seeds": len(cases),
        "passed": len(cases) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "recovery_scenarios_executed": 0,
        "live_cost": live_cost,
        "classifier": None if config is None else {
            "version": config.version, "prompt_version": config.prompt_version,
            "schema_version": config.schema_version, "configuration_hash": config.configuration_hash,
            "model_alias": config.model_alias, "reasoning_effort": config.reasoning_effort.value,
        },
        "live_invocations": [outcome.provider_result.model_dump(mode="json")
                             for _, outcome in classified_outcomes
                             if live and outcome.provider_result is not None],
    }
    report.update(_coverage(observations, cases, failures, live=live))
    return report, observations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="run paid OpenAI classifier eval after all gates")
    parser.add_argument("--report", type=Path, help="write full JSON report")
    parser.add_argument("--results", type=Path, help="write classification observations as JSONL")
    args = parser.parse_args()
    try:
        report, observations = run(live=args.live)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n")
        if args.results:
            args.results.parent.mkdir(parents=True, exist_ok=True)
            args.results.write_text("".join(row.model_dump_json() + "\n" for row in observations))
        print(
            f"Phase 2 {report['mode']} classification: {report['classification_seeds']} seeds; "
            f"{report['passed']} passed; {report['failed']} failed; no recovery scenarios executed."
        )
        if not args.live:
            print("Results are deterministic mock conformance, not live classifier accuracy.")
        for case_id, errors in report["failures"].items():
            print(f"FAIL {case_id}: {'; '.join(errors)}")
        return int(bool(report["failed"]))
    except (LiveEvalError, ValueError, OSError) as error:
        print(f"Phase 2 eval setup error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
