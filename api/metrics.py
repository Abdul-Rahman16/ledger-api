import uuid
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from api.metric_schemas import (
    NAME_PATTERN,
    MetricCreate,
    MetricIn,
    MetricList,
    MetricOut,
    MetricValidateOut,
    MetricVersionCreate,
    metric_out,
)
from core.db import get_db
from core.ratelimit import rate_limit
from core.security import Identity, get_identity
from domain import dataset_service, metric_service
from domain.metric_service import MetricConflict, MetricNotFound
from domain.metric_validator import MetricValidationError

router = APIRouter(prefix="/datasets/{dataset_id}/metrics", tags=["metrics"])

read_limit = rate_limit("read", "read_rate_limit_per_minute")
write_limit = rate_limit("metric_write", "metric_write_rate_limit_per_minute")


def _dataset_or_404(db: Session, dataset_id: uuid.UUID, identity: Identity):
    dataset = dataset_service.get_dataset(db, dataset_id)
    # 404 (not 403) so other people's datasets are indistinguishable from missing ones.
    if dataset is None or not dataset_service.can_access(dataset, identity.user_id):
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return dataset


@contextmanager
def _map_errors():
    try:
        yield
    except MetricValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MetricNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MetricConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/validate", response_model=MetricValidateOut, dependencies=[Depends(write_limit)])
def validate_definition(
    dataset_id: uuid.UUID,
    body: MetricIn,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """Dry run for live validation in the UI. Nothing is saved."""
    dataset = _dataset_or_404(db, dataset_id, identity)
    try:
        result = metric_service.validate_only(db, dataset, body.expression, body.filter)
    except MetricValidationError as exc:
        return MetricValidateOut(valid=False, error=str(exc))
    except MetricConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return MetricValidateOut(
        valid=True,
        expression=result.expression_sql,
        filter=result.filter_sql,
        columns_used=list(result.columns_used),
        aggregates_used=list(result.aggregates_used),
    )


@router.post(
    "",
    response_model=MetricOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_limit)],
)
def create_metric(
    dataset_id: uuid.UUID,
    body: MetricCreate,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    dataset = _dataset_or_404(db, dataset_id, identity)
    with _map_errors():
        metric = metric_service.create_metric(
            db, dataset, body.name, body.description, body.expression, body.filter
        )
    return metric_out(metric)


@router.get("", response_model=MetricList, dependencies=[Depends(read_limit)])
def list_metrics(
    dataset_id: uuid.UUID,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    dataset = _dataset_or_404(db, dataset_id, identity)
    return MetricList(items=[metric_out(m) for m in metric_service.list_active(db, dataset.id)])


@router.get("/{name}", response_model=MetricOut, dependencies=[Depends(read_limit)])
def get_metric(
    dataset_id: uuid.UUID,
    name: str = Path(..., pattern=NAME_PATTERN),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    dataset = _dataset_or_404(db, dataset_id, identity)
    with _map_errors():
        metric = metric_service.get_active(db, dataset.id, name)
    return metric_out(metric)


@router.get("/{name}/versions", response_model=MetricList, dependencies=[Depends(read_limit)])
def list_metric_versions(
    dataset_id: uuid.UUID,
    name: str = Path(..., pattern=NAME_PATTERN),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    dataset = _dataset_or_404(db, dataset_id, identity)
    with _map_errors():
        versions = metric_service.list_versions(db, dataset.id, name)
    return MetricList(items=[metric_out(m) for m in versions])


@router.post(
    "/{name}/versions",
    response_model=MetricOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(write_limit)],
)
def add_metric_version(
    dataset_id: uuid.UUID,
    body: MetricVersionCreate,
    name: str = Path(..., pattern=NAME_PATTERN),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    dataset = _dataset_or_404(db, dataset_id, identity)
    with _map_errors():
        metric = metric_service.create_version(
            db, dataset, name, body.description, body.expression, body.filter
        )
    return metric_out(metric)


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(write_limit)],
)
def retire_metric(
    dataset_id: uuid.UUID,
    name: str = Path(..., pattern=NAME_PATTERN),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    dataset = _dataset_or_404(db, dataset_id, identity)
    with _map_errors():
        metric_service.retire_metric(db, dataset, name)