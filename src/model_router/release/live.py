"""Deliberately small operator-only canaries, separate from offline CI."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from uuid import uuid4

from model_router.core.contracts import Classification, Request
from model_router.execution.orchestrator import execute
from model_router.release.runtime import build_app


class CanaryBlocked(ValueError):
    pass


def run_canaries(release, activation_path, journal_path, report_path, *,
                 application_id: str, max_total_cost_usd: str, run_paid: bool = False):
    """Opt-in alias calls plus one admitted classify→route→execute→V0 task.

    Uses a dedicated release application/allocation. The full application ceiling,
    not just an in-memory counter, must fit the operator's cap across restarts.
    """
    if not run_paid or os.environ.get('RUN_LIVE_OPENAI_TESTS') != '1':
        raise CanaryBlocked('explicit paid canary opt-in required')
    cap=Decimal(max_total_cost_usd)
    if not cap.is_finite() or cap <= 0:
        raise CanaryBlocked('positive finite aggregate cost cap required')
    if release.config.limits.application_cost_ceiling_usd > cap:
        raise CanaryBlocked('dedicated durable application allocation exceeds canary cap')
    if not release.config.operations.live_classifier or not release.config.operations.live_provider:
        raise CanaryBlocked('canary requires explicitly enabled provider and classifier')
    service=build_app(release,activation_path,journal_path)
    record=next((item for item in service.applications if item.application_id==application_id),None)
    if record is None or 'execute' not in record.scopes:
        raise CanaryBlocked('canary application is not authorized')
    deps=record.dependencies
    # Model retrieval is access evidence only; actual Responses calls still need
    # to succeed. No account credentials or provider exception text is reported.
    from model_router.execution.openai_provider import verify_model_access
    aliases={a:m for a,m in deps.bundle.catalog['models'].items() if m['availability']['configured_enabled']}
    access={}
    report={'schema_version':1,'release_id':release.config.release_id,
        'release_sha256':release.release_sha256,'policy_version':deps.bundle.policy['version'],
        'checked_at':datetime.now(UTC).isoformat(),'account_model_retrieval':access,
        'cost_cap_usd':str(cap),'known_spend_usd':'0','cost_complete':True,
        'raw_content_retained':False,'tasks':[],'status':'blocked'}
    destination=Path(report_path)
    # Reserve a unique report destination before any paid dispatch.
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    def retain():
        # Append snapshots; a crash leaves every previous result independently readable.
        os.write(fd,(json.dumps(report,sort_keys=True)+'\n').encode())
        os.fsync(fd)
    try:
        retain()
        access.update(verify_model_access({alias:model['provider_model_id'] for alias,model in aliases.items()},
            credential_env=release.config.live.credential_env,timeout_ms=release.config.limits.provider_timeout_ms))
        retain()
        if not all(access.values()):
            return report
        classification=Classification(task_family='transform',provenance='operator-canary-v1',confidence=1.0,
            components={name:0 for name in deps.bundle.policy['complexity']['components']})
        cases=[(alias,model['tier_rank']) for alias,model in aliases.items()]+[('end-to-end',None)]
        for label,tier in cases:
            task_id='canary-'+uuid4().hex
            request=Request(task_id=task_id,trace_id=task_id,input='Reply with OK.',
                application_id=application_id,requirements=('text_input','text_output'),consequence='low',
                context={'input_tokens':release.config.limits.max_input_tokens,
                         'expected_output_tokens':min(64,release.config.limits.max_output_tokens)},
                constraints={} if tier is None else {'model_tier_floor':tier,'model_tier_ceiling':tier})
            controls=deps.controls.model_copy(update={'idempotency_key':task_id})
            try:
                task=execute(request,replace(deps,controls=controls),
                    supplied_classification=None if tier is None else classification)
            except Exception:
                report['status']='blocked_on_uncertain_execution'
                report['cost_complete']=False
                retain()
                break
            report['tasks'].append({'canary':label,'task_id':task.task_id,'status':task.status.value,
                'total_cost_usd':None if task.total_cost_usd is None else str(task.total_cost_usd),
                'known_cost_usd':str(task.known_cost_usd),
                'failure':task.failure.cause_code if task.failure else None,
                'attempts':[a.model_dump(mode='json') for a in task.attempts]})
            report['known_spend_usd']=str(Decimal(report['known_spend_usd'])+task.known_cost_usd)
            report['cost_complete']=report['cost_complete'] and task.total_cost_usd is not None
            report['status']=('blocked_on_unknown_cost' if task.total_cost_usd is None else
                'passed' if task.status=='succeeded' and len(report['tasks'])==len(cases) else
                'running' if task.status=='succeeded' else 'failed')
            retain()
            if task.status!='succeeded' or task.total_cost_usd is None:
                break
        return report
    finally:
        os.close(fd)
