# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS dashboard
WORKDIR /build/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.10 AS uv

FROM python:3.12-slim-bookworm AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /opt/model-router
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
COPY migrations/ migrations/
COPY config/ config/
COPY docs/ docs/
COPY evals/ evals/
COPY examples/ examples/
COPY scripts/ scripts/
COPY skills/ skills/
COPY tests/ tests/
COPY dashboard/ dashboard/
COPY --from=dashboard /build/dashboard/dist dashboard/dist
RUN uv sync --locked --no-dev --extra postgres --no-editable
RUN uv build --no-sources --wheel --out-dir /dist
RUN uv pip install --python .venv/bin/python --no-deps --reinstall /dist/*.whl

FROM python:3.12-slim-bookworm AS runtime
ENV PATH=/opt/model-router/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /opt/model-router
RUN groupadd --system --gid 10001 router \
    && useradd --system --uid 10001 --gid router --home /opt/model-router router \
    && mkdir -p /var/lib/model-router /etc/model-router \
    && chown -R router:router /var/lib/model-router /etc/model-router
COPY --from=builder /opt/model-router/.venv .venv
COPY --from=builder /opt/model-router/config config
USER router
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health/live', timeout=2).read()"]
ENTRYPOINT ["model-router"]
CMD ["serve", "/opt/model-router/config/releases/route-only-v1.yaml", "--activation", "/etc/model-router/activation.json", "--journal", "/var/lib/model-router/outbox.jsonl", "--host", "0.0.0.0", "--port", "8000"]
