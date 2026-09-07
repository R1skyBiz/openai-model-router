"""ASGI concurrency boundary for explicitly activated services."""
from threading import BoundedSemaphore
from starlette.responses import JSONResponse

class ReleaseService:
    """Bound process concurrency and refresh readiness before service admission."""
    def __init__(self, app, release, check):
        self.app,self.release,self.check=app,release,check
        self.slots=BoundedSemaphore(release.config.limits.max_concurrent_tasks)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope,receive,send)
        # Detailed health is authenticated by the inner dispatcher; status remains
        # computed there using a release readiness source.
        is_action=scope.get('path') in ('/v1/route','/v1/execute','/v1/classify-route')
        if is_action and not self.slots.acquire(blocking=False):
            return await JSONResponse({'code':'concurrency_limit','retryable':True},status_code=503)(scope,receive,send)
        try:
            await self.app(scope,receive,send)
        finally:
            if is_action:
                self.slots.release()
