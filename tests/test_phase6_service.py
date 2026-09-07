"""Deterministic concurrency admission at the activated ASGI boundary."""
import asyncio
from types import SimpleNamespace
from model_router.service.release import ReleaseService


def test_concurrency_bound_rejects_before_dispatch_and_releases_slot():
    async def run():
        entered=asyncio.Event()
        proceed=asyncio.Event()
        calls=[]
        async def child(scope,receive,send):
            calls.append(scope['path'])
            entered.set()
            await proceed.wait()
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'{}'})
        release=SimpleNamespace(config=SimpleNamespace(limits=SimpleNamespace(max_concurrent_tasks=1)))
        app=ReleaseService(child,release,lambda:True)
        async def receive(): return {'type':'http.request','body':b''}
        first=[]
        second=[]
        async def send_first(message): first.append(message)
        async def send_second(message): second.append(message)
        scope={'type':'http','path':'/v1/execute'}
        pending=asyncio.create_task(app(scope,receive,send_first))
        await entered.wait()
        await app(scope,receive,send_second)
        assert second[0]['status']==503
        assert len(calls)==1
        proceed.set()
        await pending
        await app(scope,receive,send_first)
        assert len(calls)==2
        assert first[0]['status']==200
    asyncio.run(run())
