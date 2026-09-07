"""Bounded offline load/failure harness. Never constructs an OpenAI transport."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
from math import ceil
from pathlib import Path
import resource
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dataclasses import replace
from fastapi.testclient import TestClient
from model_router.execution.provider import MockProvider
from model_router.service import create_authenticated_app, AuthenticatedApplication
from hashlib import sha256
from model_router.storage.budget import SQLBudgetAuthority
from model_router.telemetry.demo import generate_demo, open_demo
from model_router.telemetry.query import TelemetryQuery
from tests.phase3_support import setup, success


def metrics(values):
    ordered=sorted(values)
    return {'count':len(values),'p50_ms':ordered[ceil(len(ordered)*.5)-1],
        'p95_ms':ordered[ceil(len(ordered)*.95)-1]}


def measure(fn, count, concurrency):
    def one(i):
        start=time.perf_counter()
        fn(i)
        return (time.perf_counter()-start)*1000
    start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        values=list(pool.map(one,range(count)))
    return {**metrics(values),'throughput_per_second':count/(time.perf_counter()-start)}


def run(directory, *, concurrency=8, requests=80, dataset=1000):
    req,cls,deps=setup(directory)
    deps=replace(deps,provider=MockProvider([success]*requests),
        budget=SQLBudgetAuthority(deps.repository,'load','allocation-v1','10','1'),
        environment=deps.environment.model_copy(update={'trusted_application_id':'load'}))
    token='offline-load-'+('x'*40)
    app=create_authenticated_app(applications=[AuthenticatedApplication('load',sha256(token.encode()).hexdigest(),deps,frozenset({'route','read','execute','health'}))])
    client=TestClient(app,headers={'Authorization':'Bearer '+token})
    body={'request':{**req.model_dump(mode='json'),'input':'Synthetic load request'},
          'classification':cls.model_dump(mode='json')}
    def route(i):
        response=client.post('/v1/route',json=body)
        assert response.status_code==200,response.text
    def execution(i):
        request={**body['request'],'task_id':f'load-{i}','trace_id':f'load-trace-{i}'}
        response=client.post('/v1/execute',json={**body,'request':request,'idempotency_key':f'load-key-{i}'})
        assert response.status_code==200,response.text
        assert response.json()['status']=='succeeded',response.text
    def retrieval(i):
        response=client.get(f'/v1/tasks/load-{i%requests}')
        assert response.status_code==200,response.text
    before=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report={'schema_version':1,'synthetic':True,'provider_time':'deterministic mock; included',
            'authentication':'per-application bearer; included','concurrency':concurrency,'requests':requests,'telemetry_dataset_tasks':dataset}
    report['route']=measure(route,requests,concurrency)
    # Also measure the shipped activated route-only composition.
    from model_router.release import load_release,activate
    from model_router.release.runtime import build_app,collect_evidence
    release=load_release(Path(__file__).resolve().parents[1]/'config/releases/route-only-v1.yaml')
    env={'MODEL_ROUTER_DATABASE_URL':str(deps.repository.engine.url),'LOAD_TOKEN':token,
        'MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON':json.dumps({'load':{'token_env':'LOAD_TOKEN','scopes':['route','read','health']}})}
    receipt=directory/'activation.json'
    journal=directory/'release-journal.jsonl'
    activate(release,environment=env,evidence=collect_evidence(release,env,journal),report_path=receipt)
    activated=build_app(release,receipt,journal,env)
    activated_client=TestClient(activated,headers={'Authorization':'Bearer '+token})
    def release_route(_):
        response=activated_client.post('/v1/route',json=body)
        assert response.status_code==200,response.text
    report['activated_route']=measure(release_route,requests,concurrency)
    report['execute']=measure(execution,requests,concurrency)
    report['retrieve']=measure(retrieval,requests,concurrency)
    report['idempotent_duplicate']=measure(execution,requests,concurrency)
    assert len(deps.provider.requests)==requests,'duplicate paid dispatch'
    generate_demo(directory/'analytics',count=dataset)
    demo=open_demo(directory/'analytics')
    query=TelemetryQuery(demo,now=lambda:datetime.now(UTC),application_scope=None,synthetic=True)
    report['telemetry_summary']=measure(lambda _:query.summary({}),12,1)
    report['dashboard_tasks']=measure(lambda _:query.tasks({},offset=0,limit=25),12,1)
    after=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    scale=1 if sys.platform=='darwin' else 1024
    report['peak_rss_growth_bytes']=(after-before)*scale
    report['outbox_pending']=len(deps.repository.pending_outbox(limit=100000))
    report['targets']={'route_p95_ms':250,'retrieve_p95_ms':250,'telemetry_p95_ms':2000,'execute_min_tasks_per_second':2}
    report['passed']=(report['route']['p95_ms']<250 and report['activated_route']['p95_ms']<250 and report['retrieve']['p95_ms']<250
        and report['telemetry_summary']['p95_ms']<2000 and report['execute']['throughput_per_second']>=2)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='evals/results/phase6-load.json')
    parser.add_argument('--concurrency',type=int,default=8)
    parser.add_argument('--requests',type=int,default=80)
    parser.add_argument('--dataset',type=int,default=1000)
    args=parser.parse_args()
    if not 1<=args.concurrency<=8 or not 8<=args.requests<=500 or not 1000<=args.dataset<=5000:
        parser.error('use concurrency 1–8, requests 8–500 and dataset 1000–5000')
    with tempfile.TemporaryDirectory(prefix='model-router-load-') as directory:
        result=run(Path(directory),concurrency=args.concurrency,requests=args.requests,dataset=args.dataset)
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
