import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.metric_schemas import metric_out
from api.query_schemas import QueryRequest, QueryResponse
from core.db import get_db
from core.ratelimit import rate_limit
from core.security import Identity, get_identity
from domain import dataset_service, query_service
from domain.query_builder import QueryRejected, QuerySpec
from domain.query_executor import QueryExecutionError, QueryTimeout
from domain.query_result import ResultInvalid

router = APIRouter(prefix="/datasets/{dataset_id}/query", tags=["query"])

query_limit = rate_limit("query", "query_rate_limit_per_minute")


@router.post("", response_model=QueryResponse, dependencies=[Depends(query_limit)])
def run_governed_query(
    dataset_id: uuid.UUID,
    body: QueryRequest,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    # 404 (not 403) so other people's datasets are indistinguishable from missing ones.
    if dataset is None or not dataset_service.can_access(dataset, identity.user_id):
        raise HTTPException(status_code=404, detail="Dataset not found.")

    spec = QuerySpec(
        metric=body.metric,
        group_by=body.group_by,
        time_grain=body.time_grain,
        date_column=body.date_column,
        date_from=body.date_from,
        date_to=body.date_to,
        order=body.order,
        limit=body.limit,
    )

    try:
        outcome = query_service.run_query(db, dataset, identity.user_id, spec)
    except QueryRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except QueryTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except QueryExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ResultInvalid as exc:
        raise HTTPException(status_code=500, detail="The result failed validation.") from exc

    return QueryResponse(
        query_id=outcome.query_id,
        metric=metric_out(outcome.metric),
        sql=outcome.display_sql,
        columns=outcome.columns,
        rows=outcome.rows,
        row_count=outcome.row_count,
        truncated=outcome.truncated,
        warnings=outcome.warnings,
    )