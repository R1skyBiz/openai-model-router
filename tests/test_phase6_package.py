from __future__ import annotations

import ast
from pathlib import Path
import tomllib

import yaml

from scripts.verify_release import VERSION, validate_source


ROOT = Path(__file__).resolve().parents[1]


def test_release_candidate_metadata_runtime_and_resources_are_declared():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == VERSION == "0.1.0rc1"
    assert "uvicorn>=0.30" in project["project"]["dependencies"]
    assert project["project"]["scripts"] == {
        "model-router": "model_router.release.cli:main"
    }
    wheel = project["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["force-include"] == {
        "migrations": "model_router/storage/alembic",
        "dashboard/dist": "model_router/dashboard",
    }
    sdist = project["tool"]["hatch"]["build"]["targets"]["sdist"]
    assert "/examples" in sdist["include"]


def test_build_verify_docker_and_workflow_files_are_parseable():
    for relative in ("scripts/build_release.py", "scripts/verify_release.py"):
        ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release-ci.yml").read_text(encoding="utf-8")
    )
    assert "verify" in workflow["jobs"]
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "npm ci" in dockerfile
    assert "uv sync --locked" in dockerfile
    assert 'ENTRYPOINT ["model-router"]' in dockerfile
    assert "USER router" in dockerfile


def test_source_configuration_and_skill_metadata_validate():
    validate_source()
