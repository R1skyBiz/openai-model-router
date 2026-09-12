"""Application-scoped authentication for the production HTTP composition."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from asyncio import timeout
from dataclasses import dataclass, replace
from hashlib import sha256
from hmac import compare_digest
import re
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope as ASGIScope, Send

from model_router.execution.orchestrator import ExecutionDependencies

from .app import create_app


Scope = Literal["route", "read", "execute", "health", "classify_route"]
_SCOPES = frozenset({"route", "read", "execute", "health", "classify_route"})
_DIGEST = re.compile(r"[0-9a-f]{64}")


def credential_digest(credential: str) -> str:
    """Return the digest stored in configuration for an opaque bearer credential."""

    if not isinstance(credential, str):
        raise TypeError("credential must be a string")
    if not credential:
        raise ValueError("credential must be non-empty")
    return sha256(credential.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AuthenticatedApplication:
    """One immutable bearer digest, application composition, and permission set."""

    application_id: str
    credential_digest: str
    dependencies: ExecutionDependencies
    scopes: frozenset[Scope]
    preview: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.application_id, str) or not self.application_id.strip():
            raise ValueError("application_id must be non-empty")
        if not isinstance(self.credential_digest, str) or not _DIGEST.fullmatch(
            self.credential_digest
        ):
            raise ValueError("credential_digest must be a lowercase SHA-256 hex digest")
        if not isinstance(self.dependencies, ExecutionDependencies):
            raise TypeError("dependencies must be an ExecutionDependencies instance")
        if self.preview is not None and self.preview.application_id != self.application_id:
            raise ValueError("preview application scope mismatch")
        normalized = frozenset(self.scopes)
        unknown = normalized - _SCOPES
        if unknown:
            raise ValueError("scopes contain unsupported values")
        if not normalized:
            raise ValueError("scopes must be non-empty")
        object.__setattr__(self, "application_id", self.application_id.strip())
        object.__setattr__(self, "scopes", normalized)


def create_authenticated_app(
    *,
    applications: Mapping[str, AuthenticatedApplication]
    | Iterable[AuthenticatedApplication],
) -> ASGIApp:
    """Create an authenticated dispatcher with permanently application-scoped apps.

    Mapping keys are credential digests and must equal the digest in their record.
    Raw bearer credentials are accepted only on individual HTTP requests.
    """

    records = _application_records(applications)
    scoped_apps: tuple[tuple[AuthenticatedApplication, FastAPI], ...] = tuple(
        (
            record,
            create_app(
                _scope_dependencies(record.dependencies, record.application_id),
                trusted_application_id=record.application_id,
                preview=record.preview,
            ),
        )
        for record in records
    )

    public_app = FastAPI(
        title="OpenAI Model Router",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @public_app.get("/health/live", include_in_schema=False)
    def health_live():
        # No configuration, identity, dependency, or provider evidence is public.
        return {"live": True}

    return _AuthenticatedDispatcher(public_app, scoped_apps)


class _AuthenticatedDispatcher:
    """Authenticate before selecting an immutable, application-scoped ASGI app."""

    def __init__(
        self,
        public_app: FastAPI,
        scoped_apps: tuple[tuple[AuthenticatedApplication, FastAPI], ...],
    ) -> None:
        self._public_app = public_app
        self._scoped_apps = scoped_apps

    async def __call__(
        self,
        scope: ASGIScope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            # The children currently declare no startup resources. Keep one
            # deterministic lifespan owner instead of request-dependent state.
            await self._public_app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/health/live":
            await self._public_app(scope, receive, send)
            return

        credential = _bearer_credential(_authorization_header(scope))
        if credential is None:
            await _auth_error(401, "authentication_required")(scope, receive, send)
            return

        supplied_digest = credential_digest(credential)
        selected: tuple[AuthenticatedApplication, FastAPI] | None = None
        # Compare against every configured digest. Do not expose whether a digest,
        # application, or scope was the failed part of authentication.
        for candidate in self._scoped_apps:
            if compare_digest(supplied_digest, candidate[0].credential_digest):
                selected = candidate
        if selected is None:
            await _auth_error(401, "authentication_required")(scope, receive, send)
            return

        required = _required_scope(path)
        if required is not None and required not in selected[0].scopes:
            await _auth_error(403, "permission_denied")(scope, receive, send)
            return

        if path == "/v1/classify-route" and selected[0].preview is not None:
            # Bound the whole ingress body, including caller correlation IDs,
            # before JSON decoding or persistence. No Content-Length trust.
            maximum = selected[0].preview.authorization.max_input_tokens
            body = bytearray()
            size = 0
            try:
                async with timeout(selected[0].preview.deadline_ms / 1000):
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        if message['type'] != 'http.request':
                            await JSONResponse(status_code=400, content={
                                'code': 'invalid_preview_body', 'retryable': False})(scope, receive, send)
                            return
                        size += len(message.get('body', b''))
                        if size > maximum:
                            await JSONResponse(status_code=413, content={
                                'code': 'preview_body_too_large', 'retryable': False})(scope, receive, send)
                            return
                        body.extend(message.get('body', b''))
                        if not message.get('more_body', False):
                            break
            except TimeoutError:
                await JSONResponse(status_code=408, content={
                    'code': 'preview_body_timeout', 'retryable': False})(scope, receive, send)
                return
            delivered = False
            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return {'type': 'http.disconnect'}
            receive = bounded_receive

        response_started = False

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await selected[1](scope, receive, tracked_send)
        except Exception:
            # FastAPI's sanitized 500 handler responds and re-raises so servers
            # can log the original exception. Stop exception text at this trust
            # boundary; no raw provider or dependency detail may enter logs.
            if not response_started:
                await _internal_error()(scope, receive, send)


def _application_records(
    applications: Mapping[str, AuthenticatedApplication]
    | Iterable[AuthenticatedApplication],
) -> tuple[AuthenticatedApplication, ...]:
    if isinstance(applications, Mapping):
        values = []
        for digest, record in applications.items():
            if not isinstance(record, AuthenticatedApplication):
                raise TypeError("applications values must be AuthenticatedApplication records")
            if digest != record.credential_digest:
                raise ValueError("applications mapping key must equal credential_digest")
            values.append(record)
        records = tuple(values)
    else:
        records = tuple(applications)
    if not records:
        raise ValueError("applications must be non-empty")
    if not all(isinstance(record, AuthenticatedApplication) for record in records):
        raise TypeError("applications must contain AuthenticatedApplication records")
    if len({record.credential_digest for record in records}) != len(records):
        raise ValueError("credential digests must be unique")
    if len({record.application_id for record in records}) != len(records):
        raise ValueError("application IDs must be unique")
    return records


def _scope_dependencies(
    dependencies: ExecutionDependencies,
    application_id: str,
) -> ExecutionDependencies:
    source = dependencies.environment
    if callable(source):
        def scoped_environment():
            return source().model_copy(
                update={"trusted_application_id": application_id}
            )

        environment = scoped_environment
    else:
        environment = source.model_copy(
            update={"trusted_application_id": application_id}
        )
    return replace(dependencies, environment=environment)


def _bearer_credential(header: str | None) -> str | None:
    if header is None:
        return None
    scheme, separator, credential = header.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not credential:
        return None
    if credential != credential.strip() or any(character.isspace() for character in credential):
        return None
    return credential


def _authorization_header(scope: ASGIScope) -> str | None:
    values = [
        value
        for name, value in scope.get("headers", ())
        if name.lower() == b"authorization"
    ]
    if len(values) != 1:
        return None
    try:
        return values[0].decode("latin-1")
    except UnicodeDecodeError:
        return None


def _required_scope(path: str) -> Scope | None:
    if path == "/v1/classify-route" or path.startswith("/v1/previews/"):
        return "classify_route"
    if path == "/v1/route":
        return "route"
    if path == "/v1/execute":
        return "execute"
    if path == "/v1/tasks" or path.startswith("/v1/tasks/"):
        return "read"
    if path == "/v1/telemetry" or path.startswith("/v1/telemetry/"):
        return "read"
    if path in {
        "/health/integration",
        "/health/ready",
        "/health/components",
        "/openapi.json",
        "/docs",
        "/redoc",
        "/docs/oauth2-redirect",
    }:
        return "health"
    return None


def _auth_error(status_code: int, code: str) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": (
                "Authentication is required."
                if status_code == 401
                else "The credential is not permitted to access this resource."
            ),
            "retryable": False,
        },
    )
    if status_code == 401:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


def _internal_error() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "The request could not be completed.",
            "retryable": True,
        },
    )


__all__ = [
    "AuthenticatedApplication",
    "Scope",
    "create_authenticated_app",
    "credential_digest",
]
