import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domain import dataset_service
from domain.metric_validator import ValidatedMetric, validate_metric
from domain.models import Dataset, MetricDefinition


class MetricNotFound(Exception):
    """No such metric (or no active version of it)."""


class MetricConflict(Exception):
    """The request conflicts with the current state of the metric or dataset."""


def _column_types(db: Session, dataset: Dataset) -> dict[str, str]:
    return {column.name: column.dtype for column in dataset_service.get_columns(db, dataset.id)}


def validate_only(db: Session, dataset: Dataset, expression: str, filter_sql: str | None) -> ValidatedMetric:
    if dataset.status != "ready":
        raise MetricConflict("The dataset is not ready yet.")
    return validate_metric(expression, filter_sql, _column_types(db, dataset))


def _versions_locked(db: Session, dataset_id: uuid.UUID, name: str) -> list[MetricDefinition]:
    """All versions of one metric, newest first, row-locked so concurrent edits serialise."""
    stmt = (
        select(MetricDefinition)
        .where(MetricDefinition.dataset_id == dataset_id, MetricDefinition.name == name)
        .order_by(MetricDefinition.version.desc())
        .with_for_update()
    )
    return list(db.scalars(stmt))


def _save(db: Session, metric: MetricDefinition) -> MetricDefinition:
    db.add(metric)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise MetricConflict("The metric was changed at the same time. Please retry.") from None
    db.refresh(metric)
    return metric


def create_metric(
    db: Session,
    dataset: Dataset,
    name: str,
    description: str | None,
    expression: str,
    filter_sql: str | None,
) -> MetricDefinition:
    validated = validate_only(db, dataset, expression, filter_sql)
    rows = _versions_locked(db, dataset.id, name)
    if any(row.is_active for row in rows):
        db.rollback()
        raise MetricConflict(f"Metric '{name}' already exists. Add a new version instead.")

    metric = MetricDefinition(
        dataset_id=dataset.id,
        name=name,
        description=description,
        sql_expression=validated.expression_sql,
        filter_sql=validated.filter_sql,
        version=rows[0].version + 1 if rows else 1,  # a retired name continues its numbering
        is_active=True,
    )
    return _save(db, metric)


def create_version(
    db: Session,
    dataset: Dataset,
    name: str,
    description: str | None,
    expression: str,
    filter_sql: str | None,
) -> MetricDefinition:
    validated = validate_only(db, dataset, expression, filter_sql)
    rows = _versions_locked(db, dataset.id, name)
    if not rows:
        db.rollback()
        raise MetricNotFound(f"Metric '{name}' does not exist.")
    active = next((row for row in rows if row.is_active), None)
    if active is None:
        db.rollback()
        raise MetricConflict(f"Metric '{name}' is retired. Create it again to reactivate it.")
    if active.sql_expression == validated.expression_sql and active.filter_sql == validated.filter_sql:
        db.rollback()
        raise MetricConflict("This definition is identical to the current version.")

    active.is_active = False
    db.flush()  # deactivate first so the one-active-version index is never violated
    new_version = MetricDefinition(
        dataset_id=dataset.id,
        name=name,
        description=description if description is not None else active.description,
        sql_expression=validated.expression_sql,
        filter_sql=validated.filter_sql,
        version=rows[0].version + 1,
        is_active=True,
    )
    return _save(db, new_version)


def retire_metric(db: Session, dataset: Dataset, name: str) -> None:
    """Soft delete: every version is kept for audit, none stays active."""
    rows = _versions_locked(db, dataset.id, name)
    active = [row for row in rows if row.is_active]
    if not active:
        db.rollback()
        raise MetricNotFound(f"Metric '{name}' does not exist.")
    for row in active:
        row.is_active = False
    db.commit()


def get_active(db: Session, dataset_id: uuid.UUID, name: str) -> MetricDefinition:
    stmt = select(MetricDefinition).where(
        MetricDefinition.dataset_id == dataset_id,
        MetricDefinition.name == name,
        MetricDefinition.is_active.is_(True),
    )
    metric = db.scalars(stmt).first()
    if metric is None:
        raise MetricNotFound(f"Metric '{name}' does not exist.")
    return metric


def list_active(db: Session, dataset_id: uuid.UUID) -> list[MetricDefinition]:
    stmt = (
        select(MetricDefinition)
        .where(MetricDefinition.dataset_id == dataset_id, MetricDefinition.is_active.is_(True))
        .order_by(MetricDefinition.name)
    )
    return list(db.scalars(stmt))


def list_versions(db: Session, dataset_id: uuid.UUID, name: str) -> list[MetricDefinition]:
    stmt = (
        select(MetricDefinition)
        .where(MetricDefinition.dataset_id == dataset_id, MetricDefinition.name == name)
        .order_by(MetricDefinition.version.desc())
    )
    rows = list(db.scalars(stmt))
    if not rows:
        raise MetricNotFound(f"Metric '{name}' does not exist.")
    return rows