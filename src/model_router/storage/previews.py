"""Dedicated preview storage, deliberately outside production task analytics."""
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from model_router.core.execution_contracts import ConcurrentUpdate, IdempotencyConflict, RepositoryUnavailable
from model_router.core.preview_contracts import RoutingPreview, PreviewCapacityExceeded
from model_router.storage.models import RoutingPreviewRow, BudgetAllocationRow


class SQLPreviewRepository:
    def __init__(self, repository, allocation_id, max_records):
        self.repository = repository
        if not allocation_id or type(max_records) is not int or max_records <= 0:
            raise ValueError('finite preview record allocation required')
        self.allocation_id, self.max_records = allocation_id, max_records

    def pin_versions(self, **versions):
        self.repository.pin_versions(**versions)

    def claim(self, preview, key_digest, request_digest):
        try:
            with self.repository._write_session() as session:
                # The existing allocation serializes claims across processes on
                # PostgreSQL; SQLite's write session already holds a writer lock.
                allocation = session.scalar(select(BudgetAllocationRow).where(
                    BudgetAllocationRow.application_id == preview.application_id,
                    BudgetAllocationRow.allocation_id == self.allocation_id).with_for_update())
                if allocation is None:
                    raise RepositoryUnavailable('preview allocation unavailable')
                existing = session.scalar(select(RoutingPreviewRow).where(
                    RoutingPreviewRow.application_id == preview.application_id,
                    RoutingPreviewRow.key_digest == key_digest))
                if existing is not None:
                    if existing.request_digest != request_digest:
                        raise IdempotencyConflict('preview identity conflicts')
                    return RoutingPreview.model_validate_json(existing.payload_json)
                count = session.scalar(select(func.count()).select_from(RoutingPreviewRow).where(
                    RoutingPreviewRow.application_id == preview.application_id,
                    RoutingPreviewRow.allocation_id == self.allocation_id))
                if count >= self.max_records:
                    raise PreviewCapacityExceeded()
                session.add(RoutingPreviewRow(
                    allocation_id=self.allocation_id,
                    preview_id=preview.preview_id, application_id=preview.application_id,
                    task_id=preview.task_id, key_digest=key_digest,
                    request_digest=request_digest, payload_json=preview.model_dump_json()))
            return None
        except IntegrityError:
            try:
                with Session(self.repository.engine) as session:
                    row = session.scalar(select(RoutingPreviewRow).where(
                        RoutingPreviewRow.application_id == preview.application_id,
                        RoutingPreviewRow.key_digest == key_digest))
                    if row is None or row.request_digest != request_digest:
                        raise IdempotencyConflict('preview identity conflicts')
                    return RoutingPreview.model_validate_json(row.payload_json)
            except SQLAlchemyError:
                raise RepositoryUnavailable('preview storage unavailable') from None
        except SQLAlchemyError:
            raise RepositoryUnavailable('preview storage unavailable') from None

    def save(self, previous, current):
        if (previous.preview_id != current.preview_id
                or previous.application_id != current.application_id):
            raise ValueError('preview identity is immutable')
        try:
            with self.repository._write_session() as session:
                statement = select(RoutingPreviewRow).where(
                    RoutingPreviewRow.preview_id == previous.preview_id,
                    RoutingPreviewRow.application_id == previous.application_id).with_for_update()
                row = session.scalar(statement)
                if row is None or row.payload_json != previous.model_dump_json():
                    raise ConcurrentUpdate('preview evidence changed')
                row.payload_json = current.model_dump_json()
        except SQLAlchemyError:
            raise RepositoryUnavailable('preview storage unavailable') from None

    def get(self, preview_id, application_id):
        try:
            with Session(self.repository.engine) as session:
                row = session.scalar(select(RoutingPreviewRow).where(
                    RoutingPreviewRow.preview_id == preview_id,
                    RoutingPreviewRow.application_id == application_id))
                return RoutingPreview.model_validate_json(row.payload_json) if row else None
        except SQLAlchemyError:
            raise RepositoryUnavailable('preview storage unavailable') from None
