"""Run the complete offline corpus through Phase 1, 2, and 3 engines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
for search_path in (ROOT, ROOT / "src"):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from evals.grader import grade
from evals.phase1_adapter import observe as observe_route
from evals.phase2_adapter import load_mock_outputs, observe as observe_classification
from evals.phase3_adapter import (
    DEFERRED_CASE,
    DEFERRED_REASON,
    observe as observe_recovery,
    observe_deferred,
)
from evals.run_local import load_cases, load_contract
from model_router.classification import MockClassifier, load_classifier_config
from model_router.policy.loader import load_bundle


def run(*, cases=None, bundle=None, classifier=None):
    corpus = load_cases() if cases is None else list(cases)
    manifest, catalog, vocabulary = load_contract()
    bundle = bundle or load_bundle(ROOT / "config")
    if classifier is None:
        config = load_classifier_config(ROOT / "config/classifier.yaml", bundle)
        classifier = MockClassifier(load_mock_outputs(), bundle, config)

    observations = []
    failures: dict[str, list[str]] = {}
    skipped = {DEFERRED_CASE: DEFERRED_REASON}
    recovery_executed = 0
    evaluator_gate = {
        "case_id": DEFERRED_CASE,
        "blocked_before_generation": False,
        "provider_dispatches": None,
        "cause_code": None,
    }

    for case in corpus:
        try:
            if case.id == DEFERRED_CASE:
                task, provider = observe_deferred(case, bundle)
                evaluator_gate.update(
                    blocked_before_generation=(
                        task.status.value == "blocked" and not task.attempts
                    ),
                    provider_dispatches=provider.call_count,
                    cause_code=None if task.failure is None else task.failure.cause_code,
                )
                if not evaluator_gate["blocked_before_generation"] or provider.call_count:
                    failures[case.id] = [
                        "deferred evaluator path did not block before generation"
                    ]
                continue
            if case.scenario is not None:
                observation, _ = observe_recovery(case, bundle)
                recovery_executed += 1
            elif case.category == "classification":
                observation, _ = observe_classification(
                    case, classifier, manifest["policy_version"]
                )
            else:
                observation = observe_route(case, bundle)
            observations.append(observation)
            errors = grade(
                case,
                observation,
                catalog,
                manifest["policy_version"],
                vocabulary,
            )
        except (KeyError, OSError, TypeError, ValueError) as error:
            errors = [f"adapter/runtime error: {type(error).__name__}: {error}"]
        if errors:
            failures[case.id] = errors

    applicable = len(corpus) - len(skipped)
    run_failures = len(failures)
    report = {
        "mode": "offline_real_execution",
        "total_corpus": len(corpus),
        "applicable": applicable,
        "passed": applicable - run_failures,
        "failed": run_failures,
        "skipped": skipped,
        "failures": failures,
        "recovery_scenarios_total": sum(case.scenario is not None for case in corpus),
        "recovery_scenarios_executed": recovery_executed,
        "recovery_scenarios_deferred": len(skipped),
        "evaluator_gate": evaluator_gate,
    }
    return report, observations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="write the complete Phase 3 report")
    parser.add_argument("--results", type=Path, help="write applicable observations as JSONL")
    args = parser.parse_args()
    try:
        report, observations = run()
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n")
        if args.results:
            args.results.parent.mkdir(parents=True, exist_ok=True)
            args.results.write_text(
                "".join(observation.model_dump_json() + "\n" for observation in observations)
            )
        print(
            f"Phase 3 corpus {report['total_corpus']}; applicable {report['applicable']}; "
            f"passed {report['passed']}; failed {report['failed']}; "
            f"recovery {report['recovery_scenarios_executed']}/"
            f"{report['recovery_scenarios_total']}."
        )
        for case_id, reason in report["skipped"].items():
            print(f"SKIP {case_id}: {reason}")
        for case_id, errors in report["failures"].items():
            print(f"FAIL {case_id}: {'; '.join(errors)}")
        return int(bool(report["failed"]))
    except (OSError, TypeError, ValueError) as error:
        print(f"Phase 3 eval setup error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
