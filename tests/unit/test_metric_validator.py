from domain.metric_validator import MetricValidationError, validate_metric

COLUMNS = {
    "order_id": "integer",
    "region": "text",
    "amount": "float",
    "order_date": "datetime",
    "status": "text",
}


def ok(expression, filter_sql=None):
    return validate_metric(expression, filter_sql, COLUMNS)


def rejected(expression, filter_sql=None):
    try:
        validate_metric(expression, filter_sql, COLUMNS)
    except MetricValidationError as exc:
        return str(exc)
    raise AssertionError(f"Expected rejection but accepted: {expression!r} / {filter_sql!r}")


def test_simple_sum_is_canonicalised_with_quoted_identifier():
    result = ok("sum(AMOUNT)")
    assert result.expression_sql == 'SUM("amount")'
    assert result.columns_used == ("amount",)
    assert result.aggregates_used == ("SUM",)


def test_count_star_and_count_distinct():
    assert ok("COUNT(*)").expression_sql == "COUNT(*)"
    assert ok("count(distinct order_id)").expression_sql == 'COUNT(DISTINCT "order_id")'
    assert ok("COUNT(region)").expression_sql == 'COUNT("region")'


def test_arithmetic_inside_aggregate():
    assert ok("SUM(amount * 2)").expression_sql == 'SUM(("amount" * 2))'
    assert ok("AVG(amount + order_id)").expression_sql == 'AVG(("amount" + "order_id"))'


def test_ratio_of_aggregates_uses_guarded_float_division():
    sql = ok("SUM(amount) / COUNT(DISTINCT order_id)").expression_sql
    assert "CAST(SUM(\"amount\") AS DOUBLE PRECISION)" in sql
    assert "NULLIF(COUNT(DISTINCT \"order_id\"), 0)" in sql


def test_percentage_expression_with_literal():
    sql = ok("100 * SUM(amount) / SUM(order_id)").expression_sql
    assert "NULLIF(SUM(\"order_id\"), 0)" in sql


def test_min_max_on_datetime_and_numeric():
    assert ok("MAX(order_date)").expression_sql == 'MAX("order_date")'
    assert ok("MIN(amount)").expression_sql == 'MIN("amount")'


def test_filter_compiles_to_rebuilt_sql():
    result = ok("SUM(amount)", "status = 'completed' AND amount > 50")
    assert result.filter_sql == "(\"status\" = 'completed' AND \"amount\" > 50)"
    assert result.columns_used == ("amount", "status")


def test_filter_forms():
    assert ok("COUNT(*)", "region IN ('North', 'South')").filter_sql == "\"region\" IN ('North', 'South')"
    assert ok("COUNT(*)", "region NOT IN ('East')").filter_sql == "\"region\" NOT IN ('East')"
    assert ok("COUNT(*)", "status IS NOT NULL").filter_sql == '"status" IS NOT NULL'
    assert ok("COUNT(*)", "status != 'refunded'").filter_sql == "\"status\" <> 'refunded'"
    assert ok("COUNT(*)", "region LIKE 'No%'").filter_sql == "\"region\" LIKE 'No%'"
    assert ok("COUNT(*)", "amount BETWEEN 10 AND 100").filter_sql == '("amount" BETWEEN 10 AND 100)'
    assert ok("COUNT(*)", "NOT (status = 'refunded')").filter_sql == "(NOT \"status\" = 'refunded')"
    assert ok("COUNT(*)", "(region = 'A' OR region = 'B') AND amount >= -5").filter_sql == (
        "((\"region\" = 'A' OR \"region\" = 'B') AND \"amount\" >= -5)"
    )


def test_datetime_filter_is_validated_and_cast():
    sql = ok("COUNT(*)", "order_date >= '2026-01-07'").filter_sql
    assert sql == "\"order_date\" >= CAST('2026-01-07' AS TIMESTAMP)"
    rejected("COUNT(*)", "order_date >= 'not a date'")


def test_string_quotes_are_re_escaped():
    sql = ok("COUNT(*)", "status = 'it''s'").filter_sql
    assert sql == "\"status\" = 'it''s'"


def test_empty_filter_is_none():
    assert ok("COUNT(*)", "   ").filter_sql is None
    assert ok("COUNT(*)", None).filter_sql is None


def test_injection_attempts_are_rejected():
    attacks = [
        "SUM(amount); DROP TABLE datasets",
        "SUM(amount) -- hi",
        "SUM(amount) /* x */",
        "SUM(amount) FROM datasets",
        "(SELECT 1)",
        "SUM((SELECT amount FROM datasets))",
        "pg_sleep(10)",
        "SUM(pg_sleep(10))",
        "SUM(amount) UNION SELECT 1",
        "SUM(\"amount\")",
        "SUM(datasets.amount)",
        "SUM(amount)::text",
        "SUM(amount) || 'x'",
        "1; SELECT 1",
        "SUM(amount) OVER ()",
        "SUM(amount) FILTER (WHERE amount > 1)",
        "SUM(amount) \x00",
        "SUM(amount) $$",
        "SUM(amount) \\",
    ]
    for attack in attacks:
        rejected(attack)


def test_filter_injection_attempts_are_rejected():
    attacks = [
        "status = 'x'; DROP TABLE datasets",
        "status = 'x' OR 1=1",
        "1 = 1",
        "status = (SELECT 'x')",
        "status = 'x' -- comment",
        "amount > 1 UNION SELECT 1",
        "status = lower('x')",
        "status = region",
        "pg_sleep(5) = 1",
        "TRUE",
        "amount > 'abc'",
        "region > 'a'",
        "amount LIKE '1%'",
        "region BETWEEN 'a' AND 'b'",
        "amount IN ()",
        "status = 'a\\b'",
    ]
    for attack in attacks:
        rejected("COUNT(*)", attack)


def test_semantic_rules():
    assert "aggregate" in rejected("amount")
    assert "inside an aggregate" in rejected("amount * 2")
    assert "aggregate" in rejected("100")
    assert "numeric" in rejected("SUM(region)")
    assert "numeric" in rejected("AVG(status)")
    assert "numeric" in rejected("MAX(region)")
    assert "numeric" in rejected("SUM(order_date)")
    assert "Division inside an aggregate" in rejected("SUM(amount / order_id)")
    assert "DISTINCT" in rejected("SUM(DISTINCT amount)")
    assert "Unknown column" in rejected("SUM(nope)")
    assert "Unknown function" in rejected("MEDIAN(amount)")
    assert "Nested" in rejected("SUM(ABS(amount))")
    assert "Nested" in rejected("COUNT(ABS(amount))")
    rejected("")
    rejected("   ")
    rejected("SUM(amount) SUM(amount)")
    rejected("SUM(amount")
    rejected("SUM()")
    rejected("COUNT(DISTINCT)")
    rejected("COUNT(order_id + 1)")


def test_unknown_column_in_filter_names_available_columns():
    message = rejected("COUNT(*)", "nope = 1")
    assert "Unknown column" in message and "amount" in message


def test_limits():
    rejected("SUM(amount)" + " + SUM(amount)" * 40)
    rejected("(" * 12 + "SUM(amount)" + ")" * 12)
    rejected("COUNT(*)", "region IN (" + ", ".join("'x'" for _ in range(60)) + ")")
    rejected("SUM(amount)", "status = '" + "a" * 600 + "'")


def test_unsupported_filter_column_type():
    columns = dict(COLUMNS, flag="boolean")
    try:
        validate_metric("COUNT(*)", "flag = 'x'", columns)
    except MetricValidationError as exc:
        assert "not support" in str(exc)
    else:
        raise AssertionError("boolean column should be rejected in filters")


def test_same_input_gives_same_canonical_form():
    a = ok("SUM(  amount )", "status='completed'")
    b = ok("sum(amount)", "STATUS = 'completed'")
    assert a.expression_sql == b.expression_sql
    assert a.filter_sql == b.filter_sql