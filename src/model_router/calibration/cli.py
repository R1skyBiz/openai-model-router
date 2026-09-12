"""Explicit calibration operator workflow, offline by construction unless opted in."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from .analytics import analyze
from .config import load_config
from .contracts import CalibrationCase
from .corpus import load_corpus, stable_id
from .intake import annotate, deduplicate, read_cases, template, write_corpus
from .reporting import json_report, render_markdown
from .storage import CalibrationStore


def _parser():
    parser = argparse.ArgumentParser(prog='model-router calibrate')
    commands = parser.add_subparsers(dest='command',required=True)
    validate = commands.add_parser('validate')
    validate.add_argument('corpus',type=Path)
    for name in ('plan','run'):
        command = commands.add_parser(name)
        command.add_argument('corpus',type=Path)
        command.add_argument('--config',required=True,type=Path)
        if name == 'run':
            mode = command.add_mutually_exclusive_group(required=True)
            mode.add_argument('--offline',action='store_true')
            mode.add_argument('--live',action='store_true')
            command.add_argument('--store',type=Path,default=Path('.calibration/runs'))
            command.add_argument('--mock-fixture',type=Path,default=Path('calibration/sample/mock-v1.json'))
    report = commands.add_parser('report')
    report.add_argument('run_id')
    report.add_argument('--store',type=Path,default=Path('.calibration/runs'))
    report.add_argument('--format',choices=('json','markdown'),default='markdown')
    review = commands.add_parser('review-output')
    review.add_argument('run_id')
    review.add_argument('candidate_id')
    review.add_argument('--store',type=Path,default=Path('.calibration/runs'))
    commands.add_parser('schema')
    commands.add_parser('template')
    ident = commands.add_parser('case-id')
    ident.add_argument('--source-ref',required=True)
    for name in ('deduplicate','annotate','import'):
        command = commands.add_parser(name)
        command.add_argument('corpus',type=Path)
        command.add_argument('--output',required=True,type=Path)
        command.add_argument('--version',required=True)
        if name == 'annotate':
            command.add_argument('--case-id',required=True)
            command.add_argument('--family')
            command.add_argument('--tag',action='append',default=[])
    from .chatgpt_export import add_parser
    add_parser(commands)
    return parser


class _LazyLiveProvider:
    """Construct SDK adapter only after the runner has admitted an invocation."""
    calibration_live_authorized = True

    def __init__(self, release):
        self.release = release
        self._provider = None
    def execute(self, request):
        if self._provider is None:
            from model_router.execution.openai_provider import OpenAIProvider
            self._provider = OpenAIProvider(self.release.policy_bundle,
                client=__import__('openai').OpenAI(
                    api_key=os.environ[self.release.config.live.credential_env],max_retries=0))
        return self._provider.execute(request)


def _live(config, bundle, classifier_config):
    from .live import LiveCalibrationGuard, LiveCalibrationBlocked
    from .grading import BlindGrader, ProviderSemanticEvaluator
    from model_router.classification import OpenAIClassifier
    from model_router.release.loader import load_release
    if os.environ.get('RUN_LIVE_CALIBRATION') != '1' or not config.live_enabled or not config.release_manifest:
        raise LiveCalibrationBlocked('explicit live configuration and opt-in required')
    release = load_release(config.release_manifest)
    provider = _LazyLiveProvider(release)
    classifier = OpenAIClassifier(provider,bundle,classifier_config)
    def evaluator(binding,purpose):
        if binding is None:
            return None
        return ProviderSemanticEvaluator(provider,binding,policy_version=bundle.policy['version'],
            catalog_version=bundle.catalog['catalog_version'],provider_model_id=bundle.catalog['models'][binding.model]['provider_model_id'],
            purpose=purpose)
    grader = BlindGrader(evaluator=evaluator(config.evaluator,'judge'),adjudicator=evaluator(config.adjudicator,'adjudication'),config=config)
    # Durable experiment allocation shared across runs; reserve before dispatch.
    from .budget import CalibrationAllocation
    if (config.allocation_id is None or config.allocation_cap_usd is None or
            config.allocation_directory is None or not Path(config.allocation_directory).is_absolute()):
        raise LiveCalibrationBlocked('an explicit durable allocation is required')
    allocation = CalibrationAllocation(config.allocation_directory,config.allocation_id,config.allocation_cap_usd)
    guard = LiveCalibrationGuard(release,allocation=allocation)
    return provider,classifier,grader,guard


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == 'export-intake':
            from .chatgpt_export import ExportRejected, run
            try:
                result = run(args)
            except ExportRejected as error:
                print(json_report({'error': 'ExportIntakeRejected', 'reason': str(error)}), end='')
                return 2
            print(json_report(result), end='')
            return 0
        if args.command == 'schema':
            print(json_report(CalibrationCase.model_json_schema()),end='')
            return 0
        if args.command == 'template':
            print(json_report(template()),end='')
            return 0
        if args.command == 'case-id':
            print(stable_id('case',args.source_ref))
            return 0
        if args.command == 'deduplicate':
            print(json_report(deduplicate(args.corpus,args.output,args.version)),end='')
            return 0
        if args.command == 'import':
            manifest = write_corpus(read_cases(args.corpus),args.output,args.version)
            load_corpus(args.output)
            print(manifest.model_dump_json(indent=2))
            return 0
        if args.command == 'annotate':
            manifest = annotate(args.corpus,args.output,args.version,args.case_id,args.family,args.tag)
            print(manifest.model_dump_json(indent=2))
            return 0
        store = CalibrationStore(args.store) if hasattr(args,'store') else None
        if args.command == 'review-output':
            print(store.load_review_output(args.run_id,args.candidate_id))
            return 0
        if args.command == 'report':
            report = analyze(store.load(args.run_id))
            print(json_report(report) if args.format == 'json' else render_markdown(report),end='')
            return 0
        cases, corpus_manifest = load_corpus(args.corpus)
        if args.command == 'validate':
            print(corpus_manifest.model_dump_json(indent=2))
            return 0
        config = load_config(args.config)
        from model_router.policy.loader import load_bundle
        from model_router.classification import load_classifier_config
        from .planning import plan_budget
        bundle = load_bundle(config.policy_directory)
        classifier_config = load_classifier_config(config.classifier_path,bundle)
        plan = plan_budget(cases,config,bundle,classifier_config)
        if args.command == 'plan':
            print(plan.model_dump_json(indent=2))
            return 0 if plan.admissible else 2
        from .runner import CalibrationRunner
        if args.offline:
            from .offline import compose_offline
            provider,classifier,grader = compose_offline(cases,bundle,classifier_config,config,args.mock_fixture)
            guard = None
        else:
            provider,classifier,grader,guard = _live(config,bundle,classifier_config)
        runner = CalibrationRunner(bundle,classifier_config,config,provider=provider,classifier=classifier,
                                   grader=grader,store=store,live_guard=guard)
        result = runner.run(cases,corpus_manifest,offline=args.offline)
        # Read the sanitized immutable result so both report formats use exactly
        # the same safe evidence available to a future read-only API.
        report = analyze(store.load(result.manifest.run_id))
        for filename,text in [('report.json',json_report(report)),('report.md',render_markdown(report))]:
            with (args.store/result.manifest.run_id/filename).open('x',encoding='utf-8') as stream:
                stream.write(text)
        print(json_report({'run_id':result.manifest.run_id,'status':result.status,
                           'report_directory':str((args.store/result.manifest.run_id).resolve()),
                           'paid_experiment_spend':report['spend']['total_paid_experiment_spend']}),end='')
        return 0 if result.status == 'completed' else 2
    except Exception:
        # Corpus, SDK, filesystem and validation errors may contain private input.
        print(json_report({'error':'CalibrationRejected','detail':'Check corpus/configuration, readiness, and retained run evidence; raw errors are suppressed.'}),end='')
        return 2
