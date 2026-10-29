"""
Governed query builder.

The caller supplies a QuerySpec (which metric, how to group, which date range).
The platform composes the SQL around the metric's stored, validated expression.
Nothing in the spec is ever pasted into SQL as free text:

  * the table name must match ds_<32 hex> and is quoted
  * columns must exist in the dataset profile and are quoted from the profile
  * date bounds are parsed to date objects and re-formatted
  * grain / order are chosen from fixed whitelists
  * the final SQL must pass assert_safe_sql, a keyword + identifier allow-list
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping

TABLE_RE = re.compile(r"^ds_[0-9a-f]{32}$")
GRAINS = ("day", "week", "month", "quarter", "year")
ORDERS = ("value_desc", "value_asc", "group_asc", "group_desc")
GROUPABLE_TYPES = {"text", "integer", "float", "datetime"}
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000

GROUP_ALIAS = "group_value"
VALUE_ALIAS = "value"

ALLOWED_WORDS = {
    "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "LIMIT", "AS",
    "AND", "OR", "NOT", "IN", "IS", "NULL", "LIKE", "BETWEEN",
    "ASC", "DESC", "NULLS", "LAST", "DISTINCT",
    "SUM", "AVG", "MIN", "MAX", "COUNT",
    "CAST", "DOUBLE", "PRECISION", "NULLIF", "TIMESTAMP", "DATE_TRUNC",
}
_SAFE_CHARS = re.compile(r"[A-Za-z0-9_\s(),.*+\-/<>=]*")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SINGLE_TABLE = re.compile(r"\bFROM\s+0\s+(?:WHERE|GROUP|ORDER|LIMIT)\b", re.IGNORECASE)


class QueryRejected(Exception):
    """The request is not allowed or not answerable. The message is safe to show the user."""


@dataclass(frozen=True)
class QuerySpec:
    metric: str
    group_by: str | None = None
    time_grain: str | None = None
    date_column: str | None = None
    date_from: date | None = None
    date_to: date | None = None  # inclusive
    order: str | None = None
    limit: int = DEFAULT_LIMIT


@dataclass(frozen=True)
class BuiltQuery:
    sql: str
    table_name: str
    grouped: bool
    limit: int  # the user-visible limit; the SQL fetches limit + 1 to detect truncation


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _scan_quotes(sql: str) -> tuple[str, list[str]]:
    """
    Walk the SQL once, left to right. Returns (sql with every quoted string / identifier
    replaced by the digit 0, list of the quoted identifiers found).
    """
    out: list[str] = []
    identifiers: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            j = i + 1
            buf: list[str] = []
            while True:
                if j >= n:
                    raise QueryRejected("The generated query was rejected (unbalanced quote).")
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:
                        buf.append(ch)
                        j += 2
                        continue
                    break
                buf.append(sql[j])
                j += 1
            if ch == '"':
                identifiers.append("".join(buf))
            out.append("0")
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out), identifiers


def assert_safe_sql(sql: str, allowed_identifiers: set[str]) -> None:
    """
    Final gate before execution. The composed SQL must be one SELECT over one table,
    use only whitelisted keywords, and reference only known quoted identifiers.
    """
    if "\\" in sql or "\x00" in sql:
        raise QueryRejected("The generated query was rejected (illegal character).")

    stripped, identifiers = _scan_quotes(sql)

    if not _SAFE_CHARS.fullmatch(stripped):
        raise QueryRejected("The generated query was rejected (illegal character).")
    if "--" in stripped or "/*" in stripped:
        raise QueryRejected("The generated query was rejected (comments are not allowed).")

    words = [word.upper() for word in _WORD.findall(stripped)]
    for word in words:
        if word not in ALLOWED_WORDS:
            raise QueryRejected("The generated query was rejected (unexpected keyword).")
    if words.count("SELECT") != 1 or words.count("FROM") != 1:
        raise QueryRejected("The generated query was rejected (subqueries are not allowed).")
    if not stripped.lstrip().upper().startswith("SELECT"):
        raise QueryRejected("The generated query was rejected (must be a SELECT).")
    if not _SINGLE_TABLE.search(stripped):
        raise QueryRejected("The generated query was rejected (exactly one table is allowed).")

    for identifier in identifiers:
        if identifier not in allowed_identifiers:
            raise QueryRejected("The generated query was rejected (unknown identifier).")


def _resolve_column(name: str, columns: Mapping[str, str], purpose: str) -> tuple[str, str]:
    lower = {real.lower(): real for real in columns}
    real = lower.get(name.strip().lower())
    if real is None:
        available = ", ".join(sorted(columns)[:30])
        raise QueryRejected(f"Unknown {purpose} column '{name[:40]}'. Available columns: {available}.")
    return real, columns[real]


def build_query(
    spec: QuerySpec,
    metric: Any,  # needs .sql_expression and .filter_sql
    table_name: str | None,
    columns: Mapping[str, str],
) -> BuiltQuery:
    if not table_name or not TABLE_RE.match(table_name):
        raise QueryRejected("This dataset has no queryable table.")
    if not isinstance(spec.limit, int) or isinstance(spec.limit, bool) or not 1 <= spec.limit <= MAX_LIMIT:
        raise QueryRejected(f"limit must be between 1 and {MAX_LIMIT}.")

    select_parts: list[str] = []
    grouped = False
    group_is_datetime = False

    if spec.group_by:
        real, dtype = _resolve_column(spec.group_by, columns, "group_by")
        if dtype not in GROUPABLE_TYPES:
            raise QueryRejected(f"Cannot group by '{real}' (type {dtype}).")
        if dtype == "datetime":
            grain = spec.time_grain or "month"
            if grain not in GRAINS:
                raise QueryRejected(f"time_grain must be one of: {', '.join(GRAINS)}.")
            group_expr = f"DATE_TRUNC('{grain}', {quote_ident(real)})"
            group_is_datetime = True
        else:
            if spec.time_grain:
                raise QueryRejected("time_grain only applies when grouping by a date column.")
            group_expr = quote_ident(real)
        select_parts.append(f"{group_expr} AS {quote_ident(GROUP_ALIAS)}")
        grouped = True
    elif spec.time_grain:
        raise QueryRejected("time_grain requires group_by.")

    select_parts.append(f"{metric.sql_expression} AS {quote_ident(VALUE_ALIAS)}")

    where_parts: list[str] = []
    if metric.filter_sql:
        where_parts.append(f"({metric.filter_sql})")

    if spec.date_from or spec.date_to:
        if not spec.date_column:
            raise QueryRejected("date_column is required when a date range is given.")
        real, dtype = _resolve_column(spec.date_column, columns, "date_column")
        if dtype != "datetime":
            raise QueryRejected(f"'{real}' is not a date column.")
        if spec.date_from and spec.date_to and spec.date_from > spec.date_to:
            raise QueryRejected("date_from must not be after date_to.")
        if spec.date_from:
            where_parts.append(f"{quote_ident(real)} >= CAST('{spec.date_from.isoformat()}' AS TIMESTAMP)")
        if spec.date_to:
            try:
                exclusive_end = spec.date_to + timedelta(days=1)
            except OverflowError:
                raise QueryRejected("date_to is out of range.") from None
            where_parts.append(f"{quote_ident(real)} < CAST('{exclusive_end.isoformat()}' AS TIMESTAMP)")
    elif spec.date_column:
        raise QueryRejected("date_column was given without date_from or date_to.")

    sql = f"SELECT {', '.join(select_parts)} FROM {quote_ident(table_name)}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)

    if grouped:
        sql += " GROUP BY 1"
        order = spec.order or ("group_asc" if group_is_datetime else "value_desc")
        if order not in ORDERS:
            raise QueryRejected(f"order must be one of: {', '.join(ORDERS)}.")
        group_col, value_col = quote_ident(GROUP_ALIAS), quote_ident(VALUE_ALIAS)
        if order == "value_desc":
            sql += f" ORDER BY {value_col} DESC NULLS LAST, {group_col} ASC NULLS LAST"
        elif order == "value_asc":
            sql += f" ORDER BY {value_col} ASC NULLS LAST, {group_col} ASC NULLS LAST"
        elif order == "group_asc":
            sql += f" ORDER BY {group_col} ASC NULLS LAST"
        else:
            sql += f" ORDER BY {group_col} DESC NULLS LAST"

    sql += f" LIMIT {spec.limit + 1}"

    assert_safe_sql(sql, {table_name, GROUP_ALIAS, VALUE_ALIAS, *columns})
    return BuiltQuery(sql=sql, table_name=table_name, grouped=grouped, limit=spec.limit)