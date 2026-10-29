from datetime import date
from types import SimpleNamespace

from domain.query_builder import (
    QueryRejected,
    QuerySpec,
    assert_safe_sql,
    build_query,
)

TABLE = "ds_" + "a" * 32
COLUMNS = {
    "order_id": "integer",
    "region": "text",
    "amount": "float",
    "order_date": "datetime",
    "status": "text",
}
METRIC = SimpleNamespace(
    name="total_revenue",
    sql_expression='SUM("amount")',
    filter_sql="\"status\" = 'completed'",
)
UNFILTERED = SimpleNamespace(name="orders", sql_expression="COUNT(*)", filter_sql=None)
ALLOWED = {TABLE, "group_value", "value", *COLUMNS}


def build(spec, metric=METRIC, table=TABLE, columns=COLUMNS):
    return build_query(spec, metric, table, columns)


def rejected(spec, metric=METRIC, table=TABLE, columns=COLUMNS):
    try:
        build_query(spec, metric, table, columns)
    except QueryRejected as exc:
        return str(exc)
    raise AssertionError(f"Expected rejection for {spec!r}")


def unsafe(sql):
    try:
        assert_safe_sql(sql, ALLOWED)
    except QueryRejected as exc:
        return str(exc)
    raise AssertionError(f"Expected unsafe: {sql!r}")


def test_ungrouped_metric_with_filter():
    built = build(QuerySpec(metric="total_revenue"))
    assert built.sql == (
        f'SELECT SUM("amount") AS "value" FROM "{TABLE}" '
        "WHERE (\"status\" = 'completed') LIMIT 101"
    )
    assert built.grouped is False and built.limit == 100


def test_metric_without_filter_has_no_where():
    sql = build(QuerySpec(metric="orders"), UNFILTERED).sql
    assert sql == f'SELECT COUNT(*) AS "value" FROM "{TABLE}" LIMIT 101'


def test_group_by_text_orders_by_value_desc_with_tiebreak():
    sql = build(QuerySpec(metric="total_revenue", group_by="Region", limit=5)).sql
    assert sql == (
        f'SELECT "region" AS "group_value", SUM("amount") AS "value" FROM "{TABLE}" '
        "WHERE (\"status\" = 'completed') GROUP BY 1 "
        'ORDER BY "value" DESC NULLS LAST, "group_value" ASC NULLS LAST LIMIT 6'
    )


def test_group_by_datetime_defaults_to_month_ascending():
    sql = build(QuerySpec(metric="orders", group_by="order_date"), UNFILTERED).sql
    assert "DATE_TRUNC('month', \"order_date\") AS \"group_value\"" in sql
    assert 'ORDER BY "group_value" ASC NULLS LAST' in sql


def test_time_grain_and_explicit_order():
    sql = build(
        QuerySpec(metric="orders", group_by="order_date", time_grain="week", order="group_desc"),
        UNFILTERED,
    ).sql
    assert "DATE_TRUNC('week'" in sql
    assert 'ORDER BY "group_value" DESC NULLS LAST' in sql
    sql = build(QuerySpec(metric="orders", group_by="region", order="value_asc"), UNFILTERED).sql
    assert 'ORDER BY "value" ASC NULLS LAST, "group_value" ASC NULLS LAST' in sql


def test_date_range_is_inclusive_of_end_date():
    sql = build(
        QuerySpec(
            metric="total_revenue",
            date_column="order_date",
            date_from=date(2026, 1, 5),
            date_to=date(2026, 1, 31),
        )
    ).sql
    assert "\"order_date\" >= CAST('2026-01-05' AS TIMESTAMP)" in sql
    assert "\"order_date\" < CAST('2026-02-01' AS TIMESTAMP)" in sql
    assert sql.count(" AND ") == 2  # filter + both bounds


def test_single_sided_date_range():
    sql = build(QuerySpec(metric="orders", date_column="order_date", date_from=date(2026, 3, 1)), UNFILTERED).sql
    assert "WHERE \"order_date\" >= CAST('2026-03-01' AS TIMESTAMP) LIMIT 101" in sql


def test_ungrouped_ignores_order_and_has_no_group_clause():
    sql = build(QuerySpec(metric="orders", order="value_desc"), UNFILTERED).sql
    assert "GROUP BY" not in sql and "ORDER BY" not in sql


def test_rejections():
    assert "Unknown group_by column" in rejected(QuerySpec(metric="m", group_by="nope"))
    assert "Available columns" in rejected(QuerySpec(metric="m", group_by="nope"))
    assert "time_grain must be" in rejected(QuerySpec(metric="m", group_by="order_date", time_grain="hour"))
    assert "only applies" in rejected(QuerySpec(metric="m", group_by="region", time_grain="month"))
    assert "requires group_by" in rejected(QuerySpec(metric="m", time_grain="month"))
    assert "order must be" in rejected(QuerySpec(metric="m", group_by="region", order="random"))
    assert "date_column is required" in rejected(QuerySpec(metric="m", date_from=date(2026, 1, 1)))
    assert "not a date column" in rejected(
        QuerySpec(metric="m", date_column="region", date_from=date(2026, 1, 1))
    )
    assert "without date_from" in rejected(QuerySpec(metric="m", date_column="order_date"))
    assert "must not be after" in rejected(
        QuerySpec(metric="m", date_column="order_date", date_from=date(2026, 2, 1), date_to=date(2026, 1, 1))
    )
    assert "limit must be" in rejected(QuerySpec(metric="m", limit=0))
    assert "limit must be" in rejected(QuerySpec(metric="m", limit=5000))
    assert "date_to is out of range" in rejected(
        QuerySpec(metric="m", date_column="order_date", date_to=date.max)
    )


def test_bad_table_names_are_rejected():
    for table in (None, "", "datasets", "ds_xyz", "ds_" + "A" * 32, 'ds_' + 'a' * 32 + '"; DROP TABLE x; --'):
        assert "no queryable table" in rejected(QuerySpec(metric="m"), table=table)


def test_group_by_unsupported_type():
    columns = dict(COLUMNS, flag="boolean")
    assert "Cannot group by" in rejected(QuerySpec(metric="m", group_by="flag"), columns=columns)


def test_tampered_stored_metric_is_stopped_by_the_final_gate():
    bad_metrics = [
        SimpleNamespace(name="x", sql_expression='SUM("amount"); DROP TABLE "x"', filter_sql=None),
        SimpleNamespace(name="x", sql_expression='SUM("password")', filter_sql=None),
        SimpleNamespace(name="x", sql_expression='(SELECT COUNT(*) FROM "datasets")', filter_sql=None),
        SimpleNamespace(name="x", sql_expression="pg_sleep(10)", filter_sql=None),
        SimpleNamespace(name="x", sql_expression="COUNT(*)", filter_sql="1=1 -- x"),
        SimpleNamespace(name="x", sql_expression="COUNT(*)", filter_sql="\"status\" = 'a\\b'"),
        SimpleNamespace(name="x", sql_expression="COUNT(*)", filter_sql="\"status\" = 'open"),
    ]
    for metric in bad_metrics:
        rejected(QuerySpec(metric="x"), metric=metric)


def test_gate_accepts_legitimate_sql_with_tricky_literals():
    ok_sql = [
        f'SELECT COUNT(*) AS "value" FROM "{TABLE}" WHERE "status" = \'a;b\'',
        f'SELECT COUNT(*) AS "value" FROM "{TABLE}" WHERE "status" = \'say "hi"\'',
        f'SELECT COUNT(*) AS "value" FROM "{TABLE}" WHERE "status" = \'it\'\'s -- fine\'',
        f'SELECT COUNT(*) AS "value" FROM "{TABLE}" WHERE "status" LIKE \'No%\'',
        f'SELECT COUNT(*) AS "value" FROM "{TABLE}" WHERE "status" = \'12:30\'',
    ]
    for sql in ok_sql:
        assert_safe_sql(sql, ALLOWED)


def test_gate_rejects_dangerous_sql():
    assert "illegal character" in unsafe(f'SELECT COUNT(*) AS "value" FROM "{TABLE}"; DROP TABLE "{TABLE}"')
    assert "comments" in unsafe(f'SELECT COUNT(*) AS "value" FROM "{TABLE}" -- x')
    assert "comments" in unsafe(f'SELECT COUNT(*) AS "value" FROM "{TABLE}" /* x */')
    assert "keyword" in unsafe(f'SELECT pg_sleep(5) AS "value" FROM "{TABLE}"')
    assert "keyword" in unsafe(f'DELETE FROM "{TABLE}"')
    assert "keyword" in unsafe(f'SELECT COUNT(*) AS "value" FROM "{TABLE}" UNION SELECT 1')
    assert "subqueries" in unsafe(f'SELECT (SELECT 1) AS "value" FROM "{TABLE}" LIMIT 1')
    assert "unknown identifier" in unsafe('SELECT COUNT(*) AS "value" FROM "pg_user" LIMIT 1')
    assert "unknown identifier" in unsafe(f'SELECT SUM("secret") AS "value" FROM "{TABLE}" LIMIT 1')
    assert "illegal character" in unsafe(f"SELECT COUNT(*) AS \"value\" FROM \"{TABLE}\" WHERE \"status\" = 'a\\b'")
    assert "unbalanced" in unsafe(f'SELECT COUNT(*) AS "value" FROM "{TABLE}" WHERE "status" = \'x')
    assert "illegal character" in unsafe(f'SELECT COUNT(*) AS "value" FROM "{TABLE}" WHERE "status" = $$x$$')
    assert "illegal character" in unsafe(f'SELECT COUNT(*) AS "value" FROM "{TABLE}"::text')


def test_two_selects_and_two_tables_are_rejected():
    assert "subqueries" in unsafe(f'SELECT COUNT(*) AS "value" FROM "{TABLE}" WHERE "amount" IN (SELECT 1)')
    assert "exactly one table" in unsafe(f'SELECT COUNT(*) AS "value" FROM "{TABLE}", "{TABLE}" LIMIT 1')
    assert "exactly one table" in unsafe(f'SELECT COUNT(*) AS "value" FROM "{TABLE}", "region" LIMIT 1')