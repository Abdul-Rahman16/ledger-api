import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from api.schemas import ColumnOut, DatasetDetail, DatasetList, DatasetOut
from core.db import get_db
from core.logging import log
from core.ratelimit import rate_limit
from core.security import Identity, get_identity
from domain import dataset_service
from domain.ingestion import MAX_UPLOAD_BYTES, IngestionError, ingest_dataset

router = APIRouter(prefix="/datasets", tags=["datasets"])

upload_limit = rate_limit("upload", "upload_rate_limit_per_minute")
read_limit = rate_limit("read", "read_rate_limit_per_minute")


def _detail(db: Session, dataset) -> DatasetDetail:
    columns = dataset_service.get_columns(db, dataset.id)
    return DatasetDetail(
        **DatasetOut.model_validate(dataset).model_dump(),
        columns=[ColumnOut.model_validate(column) for column in columns],
    )


@router.post(
    "",
    response_model=DatasetDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(upload_limit)],
)
def upload_dataset(
    file: UploadFile = File(...),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    # Plain `def` so FastAPI runs this blocking work in its threadpool.
    filename = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not filename:
        raise HTTPException(status_code=400, detail="A file name is required.")

    # Read one byte past the limit so an oversized upload is detected without
    # loading the whole thing into memory.
    content = file.file.read(MAX_UPLOAD_BYTES + 1)

    try:
        dataset = ingest_dataset(db, filename, content, user_id=identity.user_id)
    except IngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log.error("upload_failed", error=type(exc).__name__)
        raise HTTPException(status_code=500, detail="Could not store the dataset.") from exc

    return _detail(db, dataset)


@router.get("", response_model=DatasetList, dependencies=[Depends(read_limit)])
def list_datasets(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    datasets = dataset_service.list_datasets(db, identity.user_id, limit, offset)
    return DatasetList(
        items=[DatasetOut.model_validate(dataset) for dataset in datasets],
        limit=limit,
        offset=offset,
    )


@router.get("/{dataset_id}", response_model=DatasetDetail, dependencies=[Depends(read_limit)])
def get_dataset(
    dataset_id: uuid.UUID,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    # 404 (not 403) for other people's datasets, so existence is not leaked.
    if dataset is None or not dataset_service.can_access(dataset, identity.user_id):
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return _detail(db, dataset)