"""Production release CLI with measured dependency evidence only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from .activation import ActivationBlocked, activate, preflight
from .loader import ReleaseConfigurationError, load_release


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m model_router.release")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "preflight", "activate", "serve", "migrate", "live-canary"):
        command = commands.add_parser(name)
        command.add_argument("manifest", type=Path)
        if name in {"preflight", "activate", "serve", "live-canary"}:
            command.add_argument("--journal", type=Path, required=True)
        if name in {"activate", "live-canary"}:
            command.add_argument("--report", type=Path, required=True)
        if name in {"serve", "live-canary"}:
            command.add_argument("--activation", type=Path, required=True)
        if name == "serve":
            command.add_argument("--host", default="127.0.0.1")
            command.add_argument("--port", type=int, default=8000)
        if name == "live-canary":
            command.add_argument("--application", required=True)
            command.add_argument("--cap", required=True)
            command.add_argument("--run-paid", action="store_true")
    return parser


def _print(value) -> None:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    print(json.dumps(payload, sort_keys=True, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        release = load_release(args.manifest)
        if args.command == "inspect":
            _print(
                {
                    "release_id": release.config.release_id,
                    "release_sha256": release.release_sha256,
                    "enabled_operations": [
                        name
                        for name in (
                            "route", "read", "execute", "health",
                            "live_provider", "live_classifier", "tools", "shadow",
                        )
                        if getattr(release.config.operations, name)
                    ],
                }
            )
            return 0

        if args.command == "migrate":
            from model_router.storage.migrations import migrate_database

            database_url = os.environ.get(release.config.database.url_env)
            if not database_url:
                raise ValueError("database URL source is missing")
            migrate_database(database_url, release.config.database.required_migration_revision)
            _print(
                {
                    "release_id": release.config.release_id,
                    "migration_revision": release.config.database.required_migration_revision,
                    "status": "migrated",
                }
            )
            return 0

        from .runtime import build_app, collect_evidence

        if args.command == "preflight":
            result = preflight(
                release,
                evidence=collect_evidence(release, journal_path=args.journal),
            )
            _print(result)
            return 0 if result.ready else 2
        if args.command == "activate":
            result = activate(
                release,
                evidence=collect_evidence(release, journal_path=args.journal),
                report_path=args.report,
            )
            _print(result)
            return 0
        if args.command == "serve":
            if not 1 <= args.port <= 65535:
                raise ValueError("port must be between 1 and 65535")
            import uvicorn

            app = build_app(release, args.activation, args.journal)
            uvicorn.run(
                app,
                host=args.host,
                port=args.port,
                access_log=False,
                log_level="warning",
                reload=False,
                workers=1,
            )
            return 0
        if args.command == "live-canary":
            from .live import run_canaries

            result = run_canaries(
                release,
                args.activation,
                args.journal,
                args.report,
                application_id=args.application,
                max_total_cost_usd=args.cap,
                run_paid=args.run_paid,
            )
            _print(result)
            return 0 if result.get("status") == "passed" else 2
        raise AssertionError("unreachable command")
    except ActivationBlocked as exc:
        _print(exc.report)
        return 2
    except (ReleaseConfigurationError, FileExistsError, ValueError) as exc:
        _print({"error": type(exc).__name__, "detail": "Release operation rejected; inspect configuration and readiness checks."})
        return 2
    except Exception:
        # Database/SDK exceptions may contain DSNs or request material.
        _print({"error": "DependencyUnavailable", "detail": "Release operation failed safely; no exception body retained."})
        return 2


__all__ = ["main"]
