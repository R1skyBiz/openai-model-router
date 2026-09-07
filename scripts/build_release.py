"""Build the locked dashboard, wheel, and source distribution, then verify them."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path = ROOT, environment=None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=environment, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--uv", default=os.environ.get("MODEL_ROUTER_UV", "uv"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--skip-frontend-install", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    offline = ["--offline"] if args.offline else []
    _run([args.uv, "lock", "--check", *offline])
    if not args.skip_frontend_install:
        npm = ["npm", "ci"]
        if args.offline:
            npm.append("--offline")
        _run(npm, cwd=ROOT / "dashboard")
    _run(["npm", "run", "build"], cwd=ROOT / "dashboard")

    environment = os.environ.copy()
    environment.setdefault("SOURCE_DATE_EPOCH", "1788753600")
    _run(
        [
            args.uv,
            "build",
            "--no-sources",
            "--clear",
            "--out-dir",
            str(args.out_dir.resolve()),
            *offline,
            str(ROOT),
        ],
        environment=environment,
    )
    if not args.skip_verify:
        command = [
            sys.executable,
            str(ROOT / "scripts" / "verify_release.py"),
            "--artifacts-only",
            "--dist",
            str(args.out_dir.resolve()),
            "--uv",
            args.uv,
        ]
        if args.offline:
            command.append("--offline")
        _run(command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
