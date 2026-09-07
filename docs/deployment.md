# Release candidate build and deployment

The package version is `0.1.0rc1`; the candidate display version is
`v0.1.0-rc1`. No release tag or public release is created while live verification is blocked. Building an artifact does not activate a release or authorize
provider calls.

## Reproduce the artifacts

Use Python 3.12+, Node 22, npm and uv 0.12.10. The build uses both lockfiles,
compiles the dashboard, builds one wheel and one source distribution, installs
the wheel outside the checkout, and runs a packaged-migration smoke test.

```bash
uv sync --locked --all-extras
npm ci --prefix dashboard
uv run --frozen python scripts/build_release.py --skip-frontend-install --uv uv
```

Run the same offline release gates as CI when the uv and npm caches are already
populated:

```bash
uv run --frozen --offline python scripts/verify_release.py \
  --skip-frontend-install --offline --uv uv
```

The wheel contains the compiled dashboard at `model_router/dashboard` and all
Alembic revisions at `model_router/storage/alembic`. The source distribution
also contains the HTTP client example, tests, evals, configuration, dashboard
source, Dockerfile, and operator documentation.

For the unauthenticated synthetic demo, keep both processes on loopback:

```bash
uv run --frozen python scripts/generate_sample_data.py
uv run --frozen python scripts/serve_demo.py --data .demo --port 8000
npm run --prefix dashboard dev
```

## Configure and activate

Keep the database URL, bearer tokens, credential mapping, and activation receipt
outside the image and repository. The mapping points to token environment names;
it never contains a token or digest.

```bash
export MODEL_ROUTER_DATABASE_URL='sqlite+pysqlite:////var/lib/model-router/router.db'
export ROUTER_SUPPORT_TOKEN='replace-with-at-least-32-visible-ASCII-bytes'
export MODEL_ROUTER_APPLICATION_CREDENTIALS_JSON='{"support":{"token_env":"ROUTER_SUPPORT_TOKEN","scopes":["route","read","health"]}}'

model-router migrate config/releases/route-only-v1.yaml
model-router preflight config/releases/route-only-v1.yaml \
  --journal /var/lib/model-router/outbox.jsonl
model-router activate config/releases/route-only-v1.yaml \
  --journal /var/lib/model-router/outbox.jsonl \
  --report /etc/model-router/activation.json
model-router serve config/releases/route-only-v1.yaml \
  --activation /etc/model-router/activation.json \
  --journal /var/lib/model-router/outbox.jsonl
```

The default bind address is loopback. Expose a non-loopback bind only behind the
authenticated service boundary. Public liveness is limited to `/health/live`;
readiness, component health, OpenAPI, tasks, and telemetry require an authorized
application credential. The route-only candidate never enables paid execution.

## Migration, backup, and rollback

Stop admission and drain in-flight work before migration or backup. For SQLite,
use the SQLite backup API or `sqlite3 router.db ".backup backup.db"`; copying only
the main file while WAL is active is unsafe. Preserve the database, journal,
activation receipt, release manifest, and immutable policy/catalog/pricing
references together. For PostgreSQL, use a consistent `pg_dump` and retain WAL
according to the recovery-point objective.

Test restore into an isolated database, run preflight against it, reconcile the
outbox and any uncertain started provider attempts, then admit traffic. Never
resume paid execution from an older budget ledger until post-backup spend is
reconciled. Roll back schema explicitly with
`model_router.storage.downgrade_database(url, revision)` only after deploying
code compatible with that revision; take a fresh backup first.

## Container status

The multi-stage Dockerfile builds the locked dashboard and Python environment,
runs as UID 10001, disables access logs, and starts the authenticated single
process service. Mount the activation receipt at
`/etc/model-router/activation.json` and persistent state at
`/var/lib/model-router`; inject credentials and the database URL at runtime.
Publish port 8000 on loopback for local operation.

Docker was unavailable in the Phase 6 development environment, so the image
build remains an explicit release blocker until CI or an operator runs:

```bash
docker build --pull --tag openai-model-router:v0.1.0-rc1 .
docker run --rm --publish 127.0.0.1:8000:8000 \
  --env-file /secure/model-router.env \
  --mount type=bind,src=/secure/activation.json,dst=/etc/model-router/activation.json,readonly \
  --mount type=volume,src=model-router-data,dst=/var/lib/model-router \
  openai-model-router:v0.1.0-rc1
```
