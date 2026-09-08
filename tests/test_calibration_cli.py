import json
from pathlib import Path
from model_router.release.cli import main
from model_router.calibration.corpus import load_corpus, canonical_case_input_sha256
from model_router.calibration.intake import annotate, deduplicate, template, write_corpus
from model_router.calibration.contracts import CalibrationCase

CORPUS = 'calibration/sample/corpus-v1.jsonl'
CONFIG = 'config/calibration-v1.yaml'


def test_cli_validate_and_plan_are_offline(capsys):
    assert main(['calibrate','validate',CORPUS]) == 0
    assert json.loads(capsys.readouterr().out)['case_count'] == 24
    assert main(['calibrate','plan',CORPUS,'--config',CONFIG]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan['cases'] == 24 and plan['strategies'] == 3
    assert plan['maximum_classifier_calls'] == 24
    assert plan['admissible']


def test_offline_cli_sample_full_round_trip(tmp_path,capsys):
    assert main(['calibrate','run',CORPUS,'--config',CONFIG,'--offline','--store',str(tmp_path)]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response['paid_experiment_spend']['amount'] == '0'
    root = tmp_path/response['run_id']
    report = json.loads((root/'report.json').read_text())
    assert len(report['strategies']) == 3
    assert all(s['cases_recorded'] == 24 for s in report['strategies'].values())
    assert all(s['states']['PASS'] == 24 for s in report['strategies'].values())
    assert report['strategies']['ROUTER']['classifier_cost']['known_subtotal'] != '0'
    assert report['strategies']['TERRA_BASELINE']['classifier_cost']['amount'] == '0'
    assert report['spend']['experiment_overhead']['known_subtotal'] != '0'
    assert main(['calibrate','report',response['run_id'],'--store',str(tmp_path),'--format','json']) == 0
    assert json.loads(capsys.readouterr().out) == report
    assert 'Policy observations' in (root/'report.md').read_text()


def test_live_cli_refuses_environment_key_alone(tmp_path, monkeypatch,capsys):
    monkeypatch.setenv('OPENAI_API_KEY','test-only-placeholder')
    assert main(['calibrate','run',CORPUS,'--config',CONFIG,'--live','--store',str(tmp_path)]) == 2
    assert not tuple(tmp_path.iterdir())
    assert 'test-only-placeholder' not in capsys.readouterr().out


def test_errors_never_print_private_content(tmp_path,capsys):
    private = tmp_path/'input.jsonl'
    private.write_text('sensitive private input')
    assert main(['calibrate','validate',str(private)]) == 2
    assert 'sensitive private input' not in capsys.readouterr().out


def test_intake_dedup_and_annotation_preserve_router_input(tmp_path):
    case = CalibrationCase.model_validate(template())
    duplicate = case.model_copy(update={'case_id':'case-duplicate'})
    raw = tmp_path/'unreviewed.jsonl'
    raw.write_text(case.model_dump_json()+'\n'+duplicate.model_dump_json()+'\n')
    out = tmp_path/'dedup.jsonl'
    result = deduplicate(raw,out,'intake-v2')
    assert len(result['duplicates']) == 1
    cases,manifest = load_corpus(out)
    assert manifest.case_count == 1 and manifest.privacy == 'internal'
    updated = tmp_path/'annotated.jsonl'
    annotate(out,updated,'intake-v3',case.case_id,'analysis',['historical','reviewed'])
    annotated,_ = load_corpus(updated)
    assert canonical_case_input_sha256(annotated[0]) == canonical_case_input_sha256(cases[0])
    assert annotated[0].task_family_hint == 'analysis'
    assert annotated[0].tags == ('historical','reviewed')


def test_template_schema_and_case_id_cli(capsys):
    assert main(['calibrate','template']) == 0
    assert json.loads(capsys.readouterr().out)['privacy'] == 'internal'
    assert main(['calibrate','schema']) == 0
    assert 'task' in json.loads(capsys.readouterr().out)['properties']
    assert main(['calibrate','case-id','--source-ref','ticket-123']) == 0
    first = capsys.readouterr().out
    assert main(['calibrate','case-id','--source-ref','ticket-123']) == 0
    assert capsys.readouterr().out == first
    assert 'ticket-123' not in first


def test_live_cli_composition_is_admitted_without_constructing_sdk(tmp_path, monkeypatch):
    import pytest
    from tests.test_calibration_budget import _live_guard
    from model_router.calibration.cli import _live
    from model_router.calibration.live import LiveCalibrationBlocked
    from model_router.calibration.runner import CalibrationRunner
    from model_router.calibration.storage import CalibrationStore
    from model_router.classification import load_classifier_config

    _, release, config, _ = _live_guard(tmp_path / 'release')
    classifier_config = load_classifier_config('config/classifier.yaml', release.policy_bundle)
    monkeypatch.setenv('RUN_LIVE_CALIBRATION', '1')
    def forbidden(*args, **kwargs):
        raise AssertionError('SDK construction before dispatch')
    monkeypatch.setattr('openai.OpenAI', forbidden)
    provider, classifier, grader, guard = _live(
        config, release.policy_bundle, classifier_config)
    runner = CalibrationRunner(release.policy_bundle, classifier_config,
        config, provider=provider, classifier=classifier, grader=grader,
        store=CalibrationStore(tmp_path / 'runs'), live_guard=guard)
    runner._require_composition(False)
    assert provider._provider is None
    runner._source_provider = object()
    with pytest.raises(LiveCalibrationBlocked, match='adapter is not approved'):
        runner._require_composition(False)
