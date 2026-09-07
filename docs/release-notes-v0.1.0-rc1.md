# v0.1.0-rc1 — local candidate notes

**RC blocked on live verification.** No public release or package publication.
The default composition enables authenticated route/read/health only; live work
remains off regardless of credential presence.

- Versioned release loader, measured preflight, immutable activation receipt and
  explicit migration/startup commands.
- Application bearer authentication, server-derived identity, scoped execution,
  task/telemetry reads and authenticated detailed health.
- Durable SQLite/PostgreSQL task claims, allocations/reservations, outbox leases,
  cross-process journal coordination and restart/backup evidence.
- Bounded live provider/classifier admission with credential-bound account evidence,
  capped canary tooling, exact cost accounting and fail-closed unknown-cost behavior.
- Locked wheel/sdist/dashboard build, installed migration smoke, CI and deployment
  instructions; full oracle and prior-phase behavior preserved.

Live verification has not run: no account access result, paid classifier result
or end-to-end result, and $0 spent. Standard text/V0 is the only candidate live
surface. No live tools, semantic evaluators, shadows or probe scheduler are exposed.
Docker is unavailable locally; the [CI image-build gate](https://github.com/R1skyBiz/openai-model-router/actions/runs/34132794017) passed. The verified
operating envelope is deliberately small and does not certify multi-host journals
or large-scale analytics.

See [readiness](production-readiness.md), [full report](phase-6-report.md),
[integration](integration.md), and [deployment](deployment.md).
