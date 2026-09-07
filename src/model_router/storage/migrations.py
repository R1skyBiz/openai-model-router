"""Alembic entry points that work from a checkout or an installed wheel."""

from __future__ import annotations

from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config


@contextmanager
def _script_location() -> Iterator[Path]:
    packaged = files("model_router.storage").joinpath("alembic")
    if packaged.is_dir():
        with as_file(packaged) as path:
            yield path
        return
    checkout = Path(__file__).resolve().parents[3] / "migrations"
    if not checkout.is_dir():
        raise RuntimeError("packaged Alembic migrations are unavailable")
    yield checkout


def _config(database_url: str, script_location: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def migrate_database(database_url: str, revision: str) -> None:
    """Move the schema to an explicit revision."""

    with _script_location() as script_location:
        command.upgrade(_config(database_url, script_location), revision)


def upgrade_database(database_url: str) -> None:
    """Upgrade a database to the latest packaged migration."""

    migrate_database(database_url, "head")


def downgrade_database(database_url: str, revision: str = "base") -> None:
    """Explicit rollback helper used by release verification and operators."""

    with _script_location() as script_location:
        command.downgrade(_config(database_url, script_location), revision)


__all__ = ["downgrade_database", "migrate_database", "upgrade_database"]
