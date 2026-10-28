import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.models import Dataset, DatasetColumn


def can_access(dataset: Dataset, user_id: str | None) -> bool:
    """
    Guest datasets (user_id is NULL) are reachable by anyone who holds the
    unguessable UUID. Owned datasets are reachable only by their owner.
    """
    if dataset.user_id is None:
        return True
    return user_id is not None and dataset.user_id == user_id


def list_datasets(db: Session, user_id: str | None, limit: int, offset: int) -> list[Dataset]:
    if user_id is None:
        return []  # guests have no saved library
    stmt = (
        select(Dataset)
        .where(Dataset.user_id == user_id)
        .order_by(Dataset.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt))


def get_dataset(db: Session, dataset_id: uuid.UUID) -> Dataset | None:
    return db.get(Dataset, dataset_id)


def get_columns(db: Session, dataset_id: uuid.UUID) -> list[DatasetColumn]:
    stmt = (
        select(DatasetColumn)
        .where(DatasetColumn.dataset_id == dataset_id)
        .order_by(DatasetColumn.position)
    )
    return list(db.scalars(stmt))