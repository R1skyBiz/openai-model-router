"""Local ChatGPT export -> unaccepted, private owner-review proposals.

Export records are inert data. This module has no provider or network dependency.
Conversation and branch retention is deliberately conservative; owner decisions
are required to establish provenance, work-product boundaries and grading truth.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from .contracts import CalibrationCase, CorpusManifest
from .corpus import (canonical_case_input_sha256, case_content_sha256, load_corpus,
                     require_safe_identifier)
from .export_safety import (Boundary, ExportRejected, canonical, read_export, reject,
                            strict_json, write_bundle)
from .export_sanitize import load_policy

VERSION = 'chatgpt-export-intake-v1'
REVIEW_FLAGS = ['owner_privacy_review', 'origin_verification', 'task_boundary_review',
                'self_containment_review', 'independent_grading_required',
                'consequence_and_tool_review', 'cross_conversation_grouping_review']
DEFAULT_CORPORA = (
    'calibration/sample/corpus-v1.jsonl',
    'calibration/internal/real-seed-v0.jsonl',
    'calibration/internal/reviewed-pilot-v1.jsonl',
    'calibration/internal/tranche-v1/provenance-tranche-v1.jsonl',
    'calibration/internal/tranche-v2/provenance-tranche-v2.jsonl',
)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _timestamp(value):
    return value if type(value) in (float, int) and -62135596800 <= value <= 253402300799 else None


def _attachment_type(value):
    # Never emit supplied filenames, URLs, MIME subtypes or arbitrary type strings.
    if not isinstance(value, dict):
        return 'unknown'
    hint = str(value.get('mime_type', value.get('content_type', value.get('type', '')))).lower()
    if 'image' in hint:
        return 'image'
    if 'audio' in hint:
        return 'audio'
    if 'video' in hint:
        return 'video'
    if 'pdf' in hint:
        return 'pdf'
    return 'file' if hint else 'unknown'


def _turn(node, node_ref, sanitizer, counts, flags):
    message = node.get('message')
    if message is None:
        return None
    if not isinstance(message, dict):
        counts['malformed_messages'] += 1
        flags.add('malformed_message')
        return None
    author = message.get('author')
    role = author.get('role') if isinstance(author, dict) else None
    if role not in ('user', 'assistant'):
        counts['unsupported_roles'] += 1
        flags.add('omitted_role_or_tool_context')
        return None
    if message.get('status') not in (None, 'finished_successfully'):
        flags.add('incomplete_message')
        counts['incomplete_messages'] += 1
    metadata = message.get('metadata')
    metadata = metadata if isinstance(metadata, dict) else {}
    attachments = metadata.get('attachments', [])
    if not isinstance(attachments, list):
        attachments = [None]
    types = [_attachment_type(a) for a in attachments]
    content = message.get('content')
    chunks = []
    if isinstance(content, dict):
        kind = content.get('content_type')
        parts = content.get('parts')
        if kind in ('text', 'multimodal_text') and isinstance(parts, list):
            for part in parts:
                if isinstance(part, str):
                    chunks.append(part)
                else:
                    counts['unsupported_parts'] += 1
                    flags.add('unsupported_content')
                    types.append(_attachment_type(part))
        else:
            counts['unsupported_content'] += 1
            flags.add('unsupported_content')
            types.append(_attachment_type(content))
    else:
        counts['malformed_content'] += 1
        flags.add('malformed_content')
    counts['attachments'] += len(types)
    if types:
        flags.add('attachment_contents_not_imported')
    if metadata.get('is_visually_hidden_from_conversation'):
        flags.add('hidden_message')
    recipient = message.get('recipient')
    channel = message.get('channel') or metadata.get('channel')
    if recipient not in (None, 'all') or channel not in (None, 'final'):
        flags.add('omitted_role_or_tool_context')
        counts['unsupported_channels'] += 1
        chunks = []
    text = sanitizer.text('\n'.join(chunks))
    return {'message_ref': node_ref, 'role': role, 'text': text,
            'timestamp': _timestamp(message.get('create_time')),
            'attachment_types': sorted(types)}


def _category(text):
    text = text.lower()
    # Suggestions have no routing-policy effect and never establish coverage.
    for category, words in (
        ('engineering', ('pump', 'pressure', 'hvac', 'irrigation', 'humidity', 'mechanical')),
        ('coding', ('python', 'debug', 'code', 'traceback', 'function')),
        ('math', ('calculate', 'volume', 'equation', 'convert')),
        ('writing', ('draft', 'rewrite', 'letter', 'email')),
        ('analysis', ('analyze', 'compare', 'research')),
    ):
        if any(re.search(r'\b' + w + r'\b', text) for w in words):
            return category
    return 'unclassified'


def _draft(turns, case_id, candidate_id, branch_ref, group):
    users = [i for i, t in enumerate(turns) if t['role'] == 'user' and t['text'].strip()
             and not re.fullmatch(r'(?:hi|hello|thanks|thank you)[.! ]*', t['text'].strip(), re.I)]
    if not users or not any(t['role'] == 'assistant' and t['text'].strip() for t in turns[users[-1]+1:]):
        return None
    target = users[-1]
    # Historical final responses live only in the review transcript. Prior turns
    # may be necessary task context; the owner must adjudicate leakage/dependency.
    context = '\n\n'.join(t['role'].upper() + ':\n' + t['text'] for t in turns[:target] if t['text'])
    return CalibrationCase(
        case_id=case_id, corpus_version='export-review-v1', source_kind='historical_real',
        task=turns[target]['text'], context_text=context,
        context={'input_tokens': max(1, len(context) + len(turns[target]['text'])), 'expected_output_tokens': 2048},
        grading={'human_review': True, 'deterministic_authoritative': False}, privacy='restricted',
        tags=('unreviewed-export-draft',),
        notes='Unverified export derivative. Human-only draft; no success or provenance certification.',
        reference_metadata={'candidate_id': candidate_id, 'branch_ref': branch_ref,
                            'work_product_id': group, 'origin_status': 'owner_verification_required',
                            'adaptation_type': 'sanitized_branch_last_request_with_prior_context'})


def extract(records, sanitizer):
    counts = Counter(conversations=len(records))
    candidates, drafts, mappings, skipped = [], [], [], []
    seen = set()
    retained_characters = 0
    for ordinal, record in enumerate(records):
        source_hash = _hash(canonical(record))
        ref = sanitizer.ref('conversation', record.get('id') or record.get('conversation_id') or source_hash) if isinstance(record, dict) else sanitizer.ref('record', source_hash)
        if source_hash in seen:
            counts['exact_duplicate_records'] += 1
            skipped.append({'record_index': ordinal, 'reason': 'exact_duplicate_record', 'conversation_ref': ref})
            continue
        seen.add(source_hash)
        mapping = record.get('mapping') if isinstance(record, dict) else None
        if not isinstance(mapping, dict) or not mapping or len(mapping) > 10000:
            counts['skipped_conversations'] += 1
            skipped.append({'record_index': ordinal, 'reason': 'empty_or_unsupported_mapping', 'conversation_ref': ref})
            continue
        flags = set(REVIEW_FLAGS)
        parents, children = {}, {key: [] for key in mapping}
        invalid = False
        for key, node in mapping.items():
            if not isinstance(node, dict):
                invalid = True
                break
            parent = node.get('parent')
            if parent is not None and (not isinstance(parent, str) or parent not in mapping):
                invalid = True
                break
            parents[key] = parent
            if parent is not None:
                children[parent].append(key)
        leaves = sorted(k for k, v in children.items() if not v)
        paths = []
        if not invalid and leaves and len(leaves) <= 128 and len(mapping) * len(leaves) <= 100000:
            visited = set()
            for leaf in leaves:
                chain, active = [], set()
                at = leaf
                while at is not None:
                    if at in active or len(chain) >= 2048:
                        invalid = True
                        break
                    active.add(at)
                    chain.append(at)
                    at = parents[at]
                visited.update(chain)
                paths.append(list(reversed(chain)))
            invalid |= visited != set(mapping)
        else:
            invalid = True
        if invalid:
            counts['skipped_conversations'] += 1
            skipped.append({'record_index': ordinal, 'reason': 'invalid_or_unbounded_graph', 'conversation_ref': ref})
            continue
        if len(leaves) > 1:
            flags.add('branched_or_edited')
            counts['branched_conversations'] += 1
        roots = [k for k, p in parents.items() if p is None]
        if len(roots) > 1:
            flags.add('multiple_roots')
        for key, node in mapping.items():
            declared = node.get('children')
            if not isinstance(declared, list) or any(not isinstance(v, str) for v in declared) or sorted(declared) != sorted(children[key]):
                flags.add('child_links_missing_or_inconsistent')
        current = record.get('current_node')
        if not isinstance(current, str) or current not in leaves:
            flags.add('current_branch_unknown')
        turns = {}
        for key in sorted(mapping):
            node_ref = sanitizer.ref('message', [ref, key])
            turns[key] = _turn(mapping[key], node_ref, sanitizer, counts, flags)
        candidate_id = sanitizer.ref('candidate', [ref, source_hash])
        group = sanitizer.ref('work', ref)
        branches, local_drafts = [], []
        for chain in paths:
            branch_ref = sanitizer.ref('branch', [ref, chain])
            transcript = [turns[key] for key in chain if turns[key] is not None]
            retained_characters += sum(len(t['text']) for t in transcript)
            if retained_characters > 16 * 1024 * 1024:
                reject('expanded_transcript_limit')
            draft = _draft(transcript, sanitizer.ref('case', [candidate_id, branch_ref]), candidate_id, branch_ref, group)
            if draft:
                local_drafts.append(draft)
            branches.append({'branch_ref': branch_ref, 'is_current': current == chain[-1],
                             'turns': transcript, 'draft_case_id': draft.case_id if draft else None})
        if not local_drafts:
            counts['skipped_conversations'] += 1
            skipped.append({'record_index': ordinal, 'reason': 'no_complete_text_task_response_span', 'conversation_ref': ref})
            continue
        if any(b['draft_case_id'] is None for b in branches):
            flags.add('unfinished_or_unsupported_branch')
        texts = '\n'.join(t['text'] for t in turns.values() if t and t['role'] == 'user')
        category = _category(texts)
        recommendation = 'deterministic' if category == 'math' else 'semantic'
        if 'omitted_role_or_tool_context' in flags:
            recommendation = 'requires_executable_or_context_review'
        if '[REDACTED_' in texts:
            flags.add('redaction_may_affect_task_meaning')
        candidate = {'schema_version': 1, 'pipeline_version': VERSION, 'candidate_id': candidate_id,
                     'conversation_ref': ref, 'work_product_id': group, 'status': 'needs_owner_review',
                     'title_ref': sanitizer.ref('title', record.get('title')),
                     'created_at': _timestamp(record.get('create_time')),
                     'updated_at': _timestamp(record.get('update_time')),
                     'branches': branches, 'category_suggestion': category,
                     'grading_suggestion': recommendation, 'confidence': 'low',
                     'required_review': sorted(flags), 'source_record_sha256': source_hash}
        candidates.append(candidate)
        drafts.extend(local_drafts)
        mappings.append({'candidate_id': candidate_id, 'conversation_ref': ref, 'record_index': ordinal,
                         'source_record_sha256': source_hash,
                         'message_map': [{'mapping_sorted_index': i, 'message_ref': sanitizer.ref('message', [ref, key]),
                                          'parent_ref': sanitizer.ref('message', [ref, parents[key]]) if parents[key] else None}
                                         for i, key in enumerate(sorted(mapping))]})
    counts['candidates'] = len(candidates)
    counts['draft_branches'] = len(drafts)
    return candidates, drafts, mappings, skipped, dict(sorted(counts.items()))


def duplicates(drafts, comparisons):
    pool = [('candidate', c) for c in drafts] + comparisons
    if len(drafts) * len(pool) > 2000000:
        reject('duplicate_comparison_limit')
    prepared = [(origin, case, canonical_case_input_sha256(case),
                 set(re.findall(r'\w+', case.task.lower() + '\n' + case.context_text.lower())))
                for origin, case in pool]
    findings = []
    for i in range(len(drafts)):
        _, left, digest, tokens = prepared[i]
        for origin, right, other, words in prepared[i+1:]:
            union = tokens | words
            score = len(tokens & words) / len(union) if union else 0
            exact = digest == other
            if exact or score >= 0.35:
                findings.append({'candidate_case_id': left.case_id,
                                 'comparison_ref': 'comparison-' + _hash(canonical([origin, right.case_id]))[:32],
                                 'comparison_origin': origin, 'exact': exact,
                                 'jaccard': round(score, 6), 'requires_owner_grouping': True})
    return {'method': 'canonical_case_input_sha256 + task/context token-set Jaccard >= 0.35',
            'semantic_independence_established': False, 'comparison_cases': len(comparisons), 'findings': findings}


def _comparisons(boundary, paths):
    result, inventory = [], []
    defaults = paths is None
    for index, value in enumerate(DEFAULT_CORPORA if defaults else paths):
        path = boundary.repository / value if defaults else Path(value).absolute()
        ref = 'corpus-' + str(index + 1)
        if defaults and not path.exists():
            inventory.append({'corpus_ref': ref, 'status': 'missing'})
            continue
        boundary.path(path, external=False)
        cases, manifest = load_corpus(path)
        result.extend((ref, case) for case in cases)
        inventory.append({'corpus_ref': ref, 'status': 'compared', 'corpus_sha256': manifest.corpus_sha256,
                          'case_count': len(cases)})
    return result, inventory


def _bundle_files(candidates, drafts, mapping, skipped, counts, sanitizer, raw, member_count,
                  comparison, inventory):
    redactions = dict(sorted((+sanitizer.counts).items()))
    validation = {'residual_matches': dict(sanitizer.scan(candidates)),
                  'publication_safe': False, 'owner_review_required': True}
    if validation['residual_matches']:
        reject('residual_sensitive_patterns')
    candidate_bytes = b''.join(canonical(c) for c in candidates)
    draft_bytes = b''.join(canonical(d.model_dump(mode='json')) for d in drafts)
    report = {'pipeline_version': VERSION, 'counts': counts, 'archive_members': member_count,
              'accepted': 0, 'publication_safe': False, 'human_decisions': 0,
              'all_candidates_require': REVIEW_FLAGS, 'comparison_inventory': inventory}
    manifest = {'pipeline_version': VERSION, 'conversations_json_sha256': _hash(raw),
                'key_ref': sanitizer.ref('key', VERSION), 'denylist_ref': sanitizer.ref('denylist', sanitizer.terms),
                'candidate_hashes': {c['candidate_id']: _hash(canonical(c)) for c in candidates},
                'draft_case_hashes': {d.case_id: case_content_sha256(d) for d in drafts},
                'origin_verified': False, 'accepted': 0}
    groups = [{'work_product_id': c['work_product_id'], 'candidate_id': c['candidate_id'],
               'suggestion': 'retain_conversation_branches_together', 'independence_established': False}
              for c in candidates]
    files = {'candidates.jsonl': candidate_bytes, 'case-drafts.jsonl': draft_bytes,
             'candidate-mapping.json': canonical(mapping), 'review-report.json': canonical(report),
             'skipped-records.json': canonical(skipped), 'redaction-summary.json': canonical(redactions),
             'grouping-suggestions.json': canonical(groups), 'duplicates.json': canonical(comparison),
             'sanitization-validation.json': canonical(validation)}
    manifest['file_hashes'] = {name: _hash(payload) for name, payload in files.items()}
    files['provenance-manifest.json'] = canonical(manifest)
    return files


def _load_bundle(boundary, bundle, sanitizer):
    bundle = boundary.path(bundle)
    manifest = strict_json(boundary.read(bundle / 'provenance-manifest.json'))
    if manifest.get('pipeline_version') != VERSION:
        reject('unsupported_bundle_version')
    if manifest['key_ref'] != sanitizer.ref('key', VERSION) or manifest['denylist_ref'] != sanitizer.ref('denylist', sanitizer.terms):
        reject('sanitization_policy_mismatch')
    for name, digest in manifest['file_hashes'].items():
        if Path(name).name != name or _hash(boundary.read(bundle / name)) != digest:
            reject('bundle_hash_mismatch')
    raw = boundary.read(bundle / 'candidates.jsonl')
    candidates = [strict_json(line) for line in raw.splitlines() if line.strip()]
    drafts = [CalibrationCase.model_validate_json(line) for line in boundary.read(bundle / 'case-drafts.jsonl').splitlines() if line.strip()]
    if {c['candidate_id']: _hash(canonical(c)) for c in candidates} != manifest['candidate_hashes']:
        reject('candidate_hash_mismatch')
    if {c.case_id: case_content_sha256(c) for c in drafts} != manifest['draft_case_hashes']:
        reject('draft_hash_mismatch')
    if sanitizer.scan(candidates) or sanitizer.scan([d.model_dump(mode='json') for d in drafts]):
        reject('residual_sensitive_patterns')
    return candidates, drafts, manifest


def _promote(args, boundary, sanitizer):
    candidates, _, manifest = _load_bundle(boundary, args.source, sanitizer)
    proposed = [CalibrationCase.model_validate_json(line) for line in boundary.read(args.approved_cases).splitlines() if line.strip()]
    decisions = strict_json(boundary.read(args.approvals))
    if not proposed or not isinstance(decisions, list) or len(decisions) != len(proposed):
        reject('individual_approvals_required')
    by_id = {c['candidate_id']: c for c in candidates}
    approval_map = {d['case_id']: d for d in decisions}
    if len(approval_map) != len(decisions) or set(approval_map) != {c.case_id for c in proposed}:
        reject('individual_approvals_required')
    final = []
    for case in proposed:
        decision = approval_map[case.case_id]
        candidate = by_id[decision['candidate_id']]
        required = ('privacy_reviewed', 'origin_verified', 'self_contained', 'grouping_reviewed',
                    'grading_reviewed', 'independent_truth_verified', 'consequence_tools_reviewed')
        if (decision.get('decision') != 'approve' or any(decision.get(k) is not True for k in required)
                or decision.get('candidate_sha256') != manifest['candidate_hashes'][candidate['candidate_id']]
                or decision.get('approved_case_sha256') != case_content_sha256(case)):
            reject('approval_pin_or_attestation_missing')
        require_safe_identifier(decision['reviewer_ref'])
        date.fromisoformat(decision['review_date'])
        branch = decision['branch_ref']
        if branch not in {b['branch_ref'] for b in candidate['branches']}:
            reject('selected_branch_missing')
        require_safe_identifier(decision['work_product_id'])
        if not case.grading.deterministic and case.grading.rubric is None:
            reject('reviewed_grading_required')
        if 'unreviewed-export-draft' in case.tags or case.privacy == 'public':
            reject('private_reviewed_case_required')
        if sanitizer.scan(case.model_dump(mode='json')):
            reject('residual_sensitive_patterns')
        data = case.model_dump(mode='json')
        data['corpus_version'] = args.version
        data['reference_metadata'].update({
            'candidate_id': candidate['candidate_id'], 'candidate_sha256': decision['candidate_sha256'],
            'source_record_sha256': candidate['source_record_sha256'], 'branch_ref': branch,
            'work_product_id': decision['work_product_id'], 'owner_approval_sha256': _hash(canonical(decision)),
            'origin_status': 'owner_attested',
        })
        final.append(CalibrationCase.model_validate(data))
    require_safe_identifier(args.version)
    if len({canonical_case_input_sha256(c) for c in final}) != len(final):
        reject('duplicate_approved_inputs')
    raw = b''.join(canonical(c.model_dump(mode='json')) for c in final)
    corpus_manifest = CorpusManifest(corpus_version=args.version, corpus_sha256=_hash(raw), case_count=len(final),
        privacy=max((c.privacy for c in final), key=('internal', 'sensitive', 'restricted').index),
        case_hashes={c.case_id: case_content_sha256(c) for c in final},
        description='Individually owner-attested sanitized export derivatives; new corpus version.')
    # Full existing loader checks, including rubric-identity conflicts, before publish.
    files = {'corpus.jsonl': raw, 'corpus.manifest.json': canonical(corpus_manifest.model_dump(mode='json')),
             'approvals.json': canonical(decisions)}
    if sanitizer.scan(decisions):
        reject('residual_sensitive_patterns')
    write_bundle(boundary, args.output, files, validate=lambda stage: load_corpus(stage / 'corpus.jsonl'))
    return {'approved_cases': len(final), 'new_version_created': True}


def run(args):
    """Content-free error boundary shared by CLI and library callers."""
    try:
        boundary = Boundary(args.repository)
        source = boundary.path(args.source)
        output = args.output or Path.home() / 'ModelRouterPrivate/source-intake/review-v1'
        if args.action == 'preflight':
            boundary.output(output)
            with boundary.directory(source if source.is_dir() else source.parent):
                if not source.exists():
                    reject('input_missing')
            if source.is_file():
                with boundary.file(source):
                    pass
            return {'external_input': True, 'external_output': True, 'content_read': False}
        sanitizer = load_policy(boundary, args.key_file, args.denylist)
        if args.action == 'promote':
            args.output = output
            return _promote(args, boundary, sanitizer)
        if args.action in ('validate', 'duplicates'):
            _, drafts, _ = _load_bundle(boundary, source, sanitizer)
            if args.action == 'validate':
                return {'hashes_valid': True, 'residual_matches': 0, 'publication_safe': False, 'owner_review_required': True}
            comparisons, inventory = _comparisons(boundary, args.against)
            result = duplicates(drafts, comparisons)
            write_bundle(boundary, output, {'duplicates.json': canonical(result), 'comparison-inventory.json': canonical(inventory)})
            return {'duplicate_findings': len(result['findings']), 'comparison_cases': len(comparisons)}
        # Reject unsafe destinations before reading private content.
        if args.action != 'inventory':
            boundary.output(output)
        records, raw, members = read_export(boundary, source)
        candidates, drafts, mapping, skipped, counts = extract(records, sanitizer)
        if args.action == 'inventory':
            return {'counts': counts, 'archive_members': members, 'writes': 0, 'accepted': 0}
        comparisons, inventory = _comparisons(boundary, args.against)
        comparison = duplicates(drafts, comparisons)
        files = _bundle_files(candidates, drafts, mapping, skipped, counts, sanitizer, raw, members, comparison, inventory)
        write_bundle(boundary, output, files)
        return {'counts': counts, 'accepted': 0, 'review_bundle_written': True,
                'duplicate_findings': len(comparison['findings'])}
    except Exception as error:
        code = str(error) if isinstance(error, ExportRejected) else 'invalid_or_unsafe_export_operation'
        raise ExportRejected(code) from None


def add_parser(commands):
    parser = commands.add_parser('export-intake', help='Local private export proposals; never auto-accept')
    actions = parser.add_subparsers(dest='action', required=True)
    for action in ('preflight', 'inventory', 'extract', 'bundle', 'validate', 'duplicates', 'promote'):
        command = actions.add_parser(action)
        command.add_argument('source', type=Path)
        command.add_argument('--repository', type=Path, default=Path.cwd())
        command.add_argument('--output', type=Path)
        command.add_argument('--key-file', type=Path, required=action != 'preflight')
        command.add_argument('--denylist', type=Path)
        command.add_argument('--against', type=Path, action='append')
        if action == 'promote':
            command.add_argument('--approved-cases', type=Path, required=True)
            command.add_argument('--approvals', type=Path, required=True)
            command.add_argument('--version', required=True)
