"""Explicit corpus-authoring tools; never send annotations to models."""
from hashlib import sha256
import json
import os
from pathlib import Path
from .contracts import CalibrationCase, CorpusManifest
from .corpus import canonical_case_input_sha256, load_corpus, manifest_path, require_safe_identifier, stable_id

PRIVACY = ('public', 'internal', 'sensitive', 'restricted')


def read_cases(path):
    try:
        return tuple(CalibrationCase.model_validate_json(line) for line in Path(path).read_text().splitlines() if line.strip())
    except (OSError, ValueError):
        raise ValueError('invalid intake corpus') from None


def write_corpus(cases, output, version):
    require_safe_identifier(version, field='corpus_version')
    cases = tuple(CalibrationCase.model_validate({**c.model_dump(mode='json'),'corpus_version':version}) for c in cases)
    if not cases:
        raise ValueError('cannot author an empty corpus')
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError('duplicate case IDs require explicit repair')
    path = Path(output)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.exists() or manifest_path(path).exists():
        raise ValueError('intake output must be a new corpus')
    raw = ''.join(c.model_dump_json()+'\n' for c in cases).encode()
    manifest = CorpusManifest(corpus_version=version,corpus_sha256=sha256(raw).hexdigest(),case_count=len(cases),
                              privacy=max((c.privacy for c in cases),key=PRIVACY.index),
                              description='Operator-authored intake; review privacy and grading before execution.')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
    with manifest_path(path).open('x') as stream:
        stream.write(manifest.model_dump_json(indent=2)+'\n')
    return manifest


def deduplicate(source, output, version):
    retained, duplicates = {}, []
    for case in read_cases(source):
        digest = canonical_case_input_sha256(case)
        if digest in retained:
            duplicates.append({'retained':retained[digest].case_id,'duplicate':case.case_id})
        else:
            retained[digest] = case
    manifest = write_corpus(retained.values(),output,version)
    return {'corpus':manifest.model_dump(mode='json'),'duplicates':duplicates,
            'method':'exact canonical task/instructions/context/output-contract equality; semantic near-duplicates need human review'}


def annotate(source, output, version, case_id, family=None, tags=()):
    cases, _ = load_corpus(source)
    if not any(c.case_id == case_id for c in cases):
        raise ValueError('unknown case ID')
    updated = []
    for case in cases:
        if case.case_id == case_id:
            original = canonical_case_input_sha256(case)
            data = case.model_dump(mode='json')
            if family is not None:
                data['task_family_hint'] = family
            data['tags'] = tuple(dict.fromkeys((*case.tags,*tags)))
            case = CalibrationCase.model_validate(data)
            assert canonical_case_input_sha256(case) == original
        updated.append(case)
    return write_corpus(updated,output,version)


def template(version='intake-v1'):
    return CalibrationCase(case_id=stable_id('case','replace-with-safe-source-reference'),corpus_version=version,
        source_kind='historical_real',task='Replace with sanitized historical task.',
        instructions='Preserve the original task instructions.',context={'input_tokens':2048,'expected_output_tokens':512},
        grading={'human_review':True,'deterministic_authoritative':False},privacy='internal').model_dump(mode='json')
