"""Run the remaining Phase 4 case, or the combined 179-case offline corpus."""
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
from evals.phase3_adapter import DEFERRED_CASE, observe as observe_recovery
from evals.phase4_adapter import observe as observe_evaluator
from evals.phase4_regressions import run_regressions
from evals.run_local import load_cases, load_contract
from model_router.classification import MockClassifier, load_classifier_config
from model_router.policy.loader import load_bundle


def run(*, cases=None, bundle=None, classifier=None, combined: bool = False):
    corpus = load_cases() if cases is None else list(cases)
    manifest, catalog, vocabulary = load_contract()
    bundle = bundle or load_bundle(ROOT / "config")
    selected = corpus if combined else [case for case in corpus if case.id == DEFERRED_CASE]
    if classifier is None and combined:
        config = load_classifier_config(ROOT / "config/classifier.yaml", bundle)
        classifier = MockClassifier(load_mock_outputs(), bundle, config)

    observations = []
    failures: dict[str, list[str]] = {}
    evaluator_execution = None
    for case in selected:
        try:
            if case.id == DEFERRED_CASE:
                observation, evaluator_execution = observe_evaluator(case, bundle)
            elif case.scenario is not None:
                observation, _ = observe_recovery(case, bundle)
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

    run_failures = len(failures)
    gate = {
        "case_id": DEFERRED_CASE,
        "executed": evaluator_execution is not None,
        "generation_dispatches": (
            None if evaluator_execution is None else len(evaluator_execution.provider_requests)
        ),
        "evaluator_dispatches": (
            None if evaluator_execution is None else len(evaluator_execution.evaluator_requests)
        ),
        "evaluator_attempts": (
            None
            if evaluator_execution is None
            else len(evaluator_execution.task.evaluator_attempts)
        ),
        "task_status": (
            None if evaluator_execution is None else evaluator_execution.task.status.value
        ),
    }
    return {
        "mode": "offline_phase4_combined" if combined else "offline_phase4_remaining",
        "total_corpus": len(corpus),
        "applicable": len(selected),
        "passed": len(selected) - run_failures,
        "failed": run_failures,
        "failures": failures,
        "previously_covered": 0 if combined else len(corpus) - len(selected),
        "evaluator_gate": gate,
    }, observations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--combined",
        action="store_true",
        help="run all 179 cases through the Phase 1-4 adapters",
    )
    parser.add_argument(
        "--regressions",
        action="store_true",
        help="run the separate 22-case Phase 4 operational regression suite",
    )
    parser.add_argument("--report", type=Path, help="write the Phase 4 report")
    parser.add_argument("--results", type=Path, help="write applicable observations as JSONL")
    args = parser.parse_args()
    try:
        if args.combined and args.regressions:
            parser.error("--combined and --regressions are separate modes")
        report, observations = (
            run_regressions() if args.regressions else run(combined=args.combined)
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n")
        if args.results:
            args.results.parent.mkdir(parents=True, exist_ok=True)
            rows = (
                (json.dumps(observation, sort_keys=True) for observation in observations)
                if args.regressions
                else (observation.model_dump_json() for observation in observations)
            )
            args.results.write_text("".join(row + "\n" for row in rows))
        if args.regressions:
            print(
                f"Phase 4 regressions {report['total']}; passed {report['passed']}; "
                f"failed {report['failed']}."
            )
        else:
            print(
                f"Phase 4 corpus {report['total_corpus']}; applicable {report['applicable']}; "
                f"passed {report['passed']}; failed {report['failed']}."
            )
        for case_id, errors in report["failures"].items():
            print(f"FAIL {case_id}: {'; '.join(errors)}")
        return int(bool(report["failed"]))
    except (OSError, TypeError, ValueError) as error:
        print(f"Phase 4 eval setup error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
