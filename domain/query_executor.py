from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from core.db import engine
from core.logging import log

DEFAULT_TIMEOUT_MS = 5000


class QueryExecutionError(Exception):
    """The query could not be run. The message is safe to show the user."""


class QueryTimeout(QueryExecutionError):
    """The query exceeded the statement timeout."""


def execute_readonly(
    sql: str,
    max_rows: int,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> tuple[list[str], list[tuple]]:
    """
    Run one already-validated SELECT in a read-only transaction with a timeout.
    Returns (column names, rows). The transaction is always rolled back.
    """
    statement = text(sql.replace(":", "\\:"))
    try:
        with engine.connect() as conn:
            # Must be the first statement of the transaction.
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
            result = conn.execute(statement)
            columns = list(result.keys())
            rows = [tuple(row) for row in result.fetchmany(max_rows)]
            conn.rollback()
    except DBAPIError as exc:
        detail = str(getattr(exc, "orig", exc)).lower()
        if "statement timeout" in detail:
            raise QueryTimeout("The query took too long and was stopped.") from None
        log.error("query_execution_failed", error=type(exc).__name__)
        raise QueryExecutionError("The query could not be executed.") from None
    return columns, rows