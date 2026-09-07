"""Run local release gates and verify installed distribution artifacts."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import default
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import re
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0rc1"


def _run(command: list[str], *, cwd: Path = ROOT, environment=None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=environment, check=True)


def _one(directory: Path, suffix: str) -> Path:
    matches = sorted(directory.glob(f"*{suffix}"))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {suffix} artifact, found {len(matches)}")
    return matches[0]


def verify_archives(directory: Path) -> tuple[Path, Path]:
    wheel = _one(directory, ".whl")
    sdist = _one(directory, ".tar.gz")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser(policy=default).parsebytes(archive.read(metadata_name))
        assert metadata["Name"] == "openai-model-router"
        assert metadata["Version"] == VERSION
        requirements = metadata.get_all("Requires-Dist", [])
        assert any(requirement.startswith("uvicorn") for requirement in requirements)
        entry_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        assert "model-router = model_router.release.cli:main" in archive.read(entry_name).decode()
        assert "model_router/storage/alembic/env.py" in names
        assert "model_router/storage/alembic/script.py.mako" in names
        assert any(name.endswith("0003_phase6_durable_storage.py") for name in names)
        assert any(name.endswith("0004_routing_previews.py") for name in names)
        assert "model_router/execution/preview.py" in names
        assert "model_router/storage/previews.py" in names
        assert "model_router/dashboard/index.html" in names
        assert any(name.startswith("model_router/dashboard/assets/") for name in names)
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
    with tarfile.open(sdist, "r:gz") as archive:
        names = set(archive.getnames())
        assert any(name.endswith("/examples/http_client.py") for name in names)
        assert any(name.endswith("/hatch_build.py") for name in names)
        assert any(name.endswith("/dashboard/dist/index.html") for name in names)
        assert any(name.endswith("/migrations/versions/0003_phase6_durable_storage.py") for name in names)
        assert any(name.endswith("/config/releases/leo-shadow-v1.yaml") for name in names)
        assert any(name.endswith("/scripts/compose_leo_preview.py") for name in names)
        assert not any("node_modules/" in name or "__pycache__" in name for name in names)
    return wheel, sdist


def verify_installed_wheel(wheel: Path, uv: str, *, offline: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="model-router-wheel-") as raw:
        temporary = Path(raw)
        target = temporary / "site"
        command = [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--no-deps",
            "--target",
            str(target),
        ]
        if offline:
            command.append("--offline")
        command.append(str(wheel))
        _run(command, cwd=temporary)
        smoke = """
import sys
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
sys.path.insert(0, sys.argv[1])
assert version('openai-model-router') == '0.1.0rc1'
assert files('model_router.storage').joinpath('alembic/env.py').is_file()
assert files('model_router').joinpath('dashboard/index.html').is_file()
from model_router.storage.migrations import downgrade_database, upgrade_database
url = 'sqlite+pysqlite:///' + str(Path(sys.argv[2]) / 'installed.db')
upgrade_database(url)
downgrade_database(url)
upgrade_database(url)
from sqlalchemy import create_engine, inspect
assert 'routing_previews' in inspect(create_engine(url)).get_table_names()
from model_router.execution.preview import classify_route
from model_router.storage.previews import SQLPreviewRepository
from model_router.release.cli import main
assert callable(main)
"""
        _run(
            [sys.executable, "-I", "-c", smoke, str(target), str(temporary)],
            cwd=temporary,
        )


def validate_source() -> None:
    tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for directory in (ROOT / "config", ROOT / "evals" / "phase2_data"):
        for path in directory.rglob("*.yaml"):
            yaml.safe_load(path.read_text(encoding="utf-8"))
    for path in (ROOT / "skills").glob("*/SKILL.md"):
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n")
        _, frontmatter, _ = text.split("---", 2)
        values = yaml.safe_load(frontmatter)
        assert values.get("name") and values.get("description")
        for reference in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if "://" not in reference and not reference.startswith("#"):
                assert (path.parent / reference).resolve().exists(), (
                    f"broken skill link: {path}:{reference}"
                )
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    secret_patterns = (
        re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    for encoded in tracked:
        if not encoded:
            continue
        path = ROOT / os.fsdecode(encoded)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        assert not any(pattern.search(content) for pattern in secret_patterns), (
            f"possible committed secret: {path.relative_to(ROOT)}"
        )


def verify_clean_editable(uv: str, *, offline: bool) -> None:
    """Exercise fresh Python setup with no generated frontend directory."""
    with tempfile.TemporaryDirectory(prefix='model-router-clean-') as raw:
        checkout = Path(raw)
        for name in ('pyproject.toml', 'uv.lock', 'README.md', 'hatch_build.py'):
            shutil.copy2(ROOT / name, checkout / name)
        for name in ('src', 'migrations'):
            shutil.copytree(ROOT / name, checkout / name, ignore=shutil.ignore_patterns('__pycache__'))
        assert not (checkout / 'dashboard').exists()
        _run([uv, 'sync', '--locked', '--no-dev', '--python', sys.executable,
            *(['--offline'] if offline else [])], cwd=checkout)
        _run([str(checkout / '.venv' / 'bin' / 'python'), '-I', '-c',
            'from model_router.service import create_app; from model_router.release.cli import main'], cwd=checkout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--uv", default=os.environ.get("MODEL_ROUTER_UV", "uv"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--artifacts-only", action="store_true")
    parser.add_argument("--skip-frontend-install", action="store_true")
    args = parser.parse_args()
    args.dist = args.dist.resolve()

    if not args.artifacts_only:
        validate_source()
        offline = ["--offline"] if args.offline else []
        _run([args.uv, "lock", "--check", *offline])
        _run(["git", "diff", "--check"])
        _run(
            [
                "git",
                "diff",
                "--exit-code",
                "471128e1504b7e7218d6c1b297d30955824973b3",
                "--",
                "config/models.yaml",
                "config/routing-policy.yaml",
                "config/budgets.yaml",
                "config/validation.yaml",
                "evals/cases",
                "evals/fixtures",
                "evals/grader.py",
                "evals/schema.py",
                "evals/schema",
            ]
        )
        _run([args.uv, "run", "--frozen", *offline, "pytest"])
        for command in (
            ["python", "evals/run_phase1.py"],
            ["python", "evals/run_phase2.py"],
            ["python", "evals/run_phase3.py"],
            ["python", "evals/run_phase4.py"],
            ["python", "evals/run_phase4.py", "--combined"],
            ["python", "evals/run_phase4.py", "--regressions"],
        ):
            _run([args.uv, "run", "--frozen", *offline, *command])
        with tempfile.TemporaryDirectory(prefix="model-router-load-report-") as raw:
            _run(
                [
                    args.uv,
                    "run",
                    "--frozen",
                    *offline,
                    "python",
                    "scripts/load_release.py",
                    "--output",
                    str(Path(raw) / "load.json"),
                ]
            )
        if not args.skip_frontend_install:
            npm = ["npm", "ci"] + (["--offline"] if args.offline else [])
            _run(npm, cwd=ROOT / "dashboard")
        for command in (["npm", "test"], ["npm", "run", "typecheck"], ["npm", "run", "build"]):
            _run(command, cwd=ROOT / "dashboard")
        build = [
            sys.executable,
            str(ROOT / "scripts" / "build_release.py"),
            "--out-dir",
            str(args.dist),
            "--uv",
            args.uv,
            "--skip-frontend-install",
            "--skip-verify",
        ]
        if args.offline:
            build.append("--offline")
        _run(build)

    wheel, _sdist = verify_archives(args.dist)
    verify_installed_wheel(wheel, args.uv, offline=args.offline)
    verify_clean_editable(args.uv, offline=args.offline)
    print(f"verified {wheel.name} and installed-wheel migration smoke", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
