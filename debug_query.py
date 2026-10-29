"""Temporary debug helper. Delete after use."""
import uuid

from sqlalchemy import text

from core.db import SessionLocal, engine
from domain import dataset_service, metric_service
from domain.models import Dataset
from domain.query_builder import QuerySpec, build_query

DATASET_ID = "c56d392e-99ea-4ecd-9e51-2fd71aff8740"

db = SessionLocal()
dataset = db.get(Dataset, uuid.UUID(DATASET_ID))
metric = metric_service.get_active(db, dataset.id, "total_revenue")
columns = {c.name: c.dtype for c in dataset_service.get_columns(db, dataset.id)}
print("table:", dataset.table_name)
print("columns:", columns)

built = build_query(QuerySpec(metric="total_revenue"), metric, dataset.table_name, columns)
print("sql:", built.sql)

statement = text(built.sql.replace(":", "\\:"))
with engine.connect() as conn:
    for label, sql in [
        ("read only", "SET TRANSACTION READ ONLY"),
        ("timeout", "SET LOCAL statement_timeout = 5000"),
    ]:
        try:
            conn.execute(text(sql))
            print("ok:", label)
        except Exception as exc:
            print("FAILED at:", label)
            print(type(exc).__name__, getattr(exc, "orig", exc))
            raise SystemExit(1)
    try:
        result = conn.execute(statement)
        print("result columns:", list(result.keys()))
        print("rows:", result.fetchmany(5))
    except Exception as exc:
        print("QUERY FAILED:", type(exc).__name__)
        print(getattr(exc, "orig", exc))