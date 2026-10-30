import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.ask_schemas import AskRequest, AskResponse, ask_response
from core.db import get_db
from core.llm_types import LLMUnavailable
from core.ratelimit import rate_limit
from core.security import Identity, get_identity
from domain import ask_service, dataset_service
from domain.query_builder import QueryRejected
from domain.query_executor import QueryExecutionError, QueryTimeout
from domain.query_result import ResultInvalid

router = APIRouter(prefix="/datasets/{dataset_id}/ask", tags=["ask"])

ask_limit = rate_limit("ask", "ask_rate_limit_per_minute")


@router.post("", response_model=AskResponse, dependencies=[Depends(ask_limit)])
def ask(
    dataset_id: uuid.UUID,
    body: AskRequest,
    identity: Identity = Depends(get_identity),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    # 404 (not 403) so other people's datasets are indistinguishable from missing ones.
    if dataset is None or not dataset_service.can_access(dataset, identity.user_id):
        raise HTTPException(status_code=404, detail="Dataset not found.")

    try:
        outcome = ask_service.ask_question(db, dataset, identity.user_id, body.question)
    except QueryRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except QueryTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except QueryExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ResultInvalid as exc:
        raise HTTPException(status_code=500, detail="The result failed validation.") from exc

    return ask_response(outcome)