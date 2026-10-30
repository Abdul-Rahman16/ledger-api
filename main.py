from fastapi import FastAPI

from api.ask import router as ask_router
from api.datasets import router as datasets_router
from api.metrics import router as metrics_router
from api.query import router as query_router

app = FastAPI(title="Ledger API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(datasets_router)
app.include_router(metrics_router)
app.include_router(query_router)
app.include_router(ask_router)