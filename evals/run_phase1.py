"""Run all applicable independent envelopes through the real offline router."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from evals.grader import grade
from evals.phase1_adapter import observe, skip_reason
from evals.run_local import load_cases, load_contract
from model_router.policy.loader import load_bundle


def run():
    cases = load_cases()
    manifest, catalog, vocabulary = load_contract()
    bundle = load_bundle(ROOT / "config")
    observations, failures, skipped = [], {}, {}
    boundaries, anti_astra = {}, {}
    for case in cases:
        reason = skip_reason(case)
        if reason:
            skipped[case.id] = reason
            continue
        try:
            observation = observe(case, bundle)
            observations.append(observation)
            errors = grade(case, observation, catalog, manifest["policy_version"], vocabulary)
        except (ValueError, TypeError, KeyError) as error:
            errors = [f"adapter/runtime error: {type(error).__name__}: {error}"]
        if errors:
            failures[case.id] = errors
        if "boundary" in case.tags:
            boundaries[case.id] = not bool(errors)
        if "astra" in case.expected.forbidden_models:
            anti_astra[case.id] = not bool(errors)
    applicable = len(cases) - len(skipped)
    return dict(total_corpus=len(cases), applicable=applicable, passed=applicable-len(failures),
                failed=len(failures), skipped=skipped, failures=failures, boundaries=boundaries,
                must_not_use_astra=anti_astra), observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="write full JSON report including every skipped ID/reason")
    parser.add_argument("--results", type=Path, help="write actual observation JSONL for the independent grader")
    args = parser.parse_args()
    report, observations = run()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    if args.results:
        args.results.parent.mkdir(parents=True, exist_ok=True)
        args.results.write_text("".join(result.model_dump_json() + "\n" for result in observations))
    print(f"Corpus {report['total_corpus']}; applicable {report['applicable']}; "
          f"passed {report['passed']}; failed {report['failed']}; skipped {len(report['skipped'])}.")
    for case_id, reason in report["skipped"].items():
        print(f"SKIP {case_id}: {reason}")
    for case_id, errors in report["failures"].items():
        print(f"FAIL {case_id}: {'; '.join(errors)}")
    return int(bool(report["failed"]))


if __name__ == "__main__":
    raise SystemExit(main())
