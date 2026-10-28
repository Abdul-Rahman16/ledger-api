"""
Metric expression / filter validator and compiler.

A metric is NOT free-form SQL. It is a tiny, closed language:

  expression := aggregates combined with + - * / and number literals
                e.g. SUM(amount), SUM(amount) / COUNT(DISTINCT order_id)
  filter     := boolean conditions on columns (optional)
                e.g. status = 'completed' AND amount > 50

The text is tokenized and parsed by a hand-written allow-list parser. Anything
outside the grammar is rejected, and the SQL that is stored and later executed
is REBUILT from the parsed structure (quoted identifiers, re-escaped literals,
guarded division). The user's original text is never executed or interpolated.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

MAX_EXPRESSION_CHARS = 300
MAX_FILTER_CHARS = 500
MAX_TOKENS = 200
MAX_DEPTH = 8
MAX_IN_ITEMS = 50
MAX_NUMBER_CHARS = 20

AGGREGATES = {"SUM", "AVG", "MIN", "MAX", "COUNT"}
NUMERIC_TYPES = {"integer", "float"}
COMPARISONS = {"=", "!=", "<>", "<", "<=", ">", ">="}
EQUALITY_ONLY = {"=", "!=", "<>"}
KEYWORDS = {"AND", "OR", "NOT", "IN", "IS", "NULL", "LIKE", "BETWEEN", "DISTINCT"} | AGGREGATES

_TOKEN_RE = re.compile(
    r"\s*(?:"
    r"(?P<number>\d+(?:\.\d+)?)"
    r"|(?P<string>'(?:[^']|'')*')"
    r"|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op><=|>=|<>|!=|[=<>+\-*/(),])"
    r")"
)


class MetricValidationError(Exception):
    """The metric definition is not allowed. The message is safe to show the user."""


@dataclass(frozen=True)
class ValidatedMetric:
    expression_sql: str
    filter_sql: str | None
    columns_used: tuple[str, ...]
    aggregates_used: tuple[str, ...]


@dataclass(frozen=True)
class _Token:
    kind: str  # number, string, ident, op
    value: str
    pos: int


def _tokenize(text: str) -> list[_Token]:
    text = text.strip()
    if "--" in text or "/*" in text or "*/" in text:
        raise MetricValidationError("Comments are not allowed.")
    tokens: list[_Token] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None or match.end() == pos:
            bad = text[pos:].lstrip()[:1] or text[pos : pos + 1]
            raise MetricValidationError(f"Unexpected character {bad!r}.")
        kind = match.lastgroup
        tokens.append(_Token(kind, match.group(kind), match.start(kind)))
        pos = match.end()
        if len(tokens) > MAX_TOKENS:
            raise MetricValidationError("Definition is too long.")
    return tokens


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class _Parser:
    def __init__(self, tokens: list[_Token], columns: Mapping[str, str]) -> None:
        self.tokens = tokens
        self.i = 0
        self.depth = 0
        self.columns = dict(columns)
        self._lower = {name.lower(): name for name in columns}
        self.columns_used: set[str] = set()
        self._arg_cols: list[str] = []
        self.aggregates_used: set[str] = set()

    # ---------- token helpers ----------
    def _peek(self, offset: int = 0) -> _Token | None:
        index = self.i + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def _next(self) -> _Token:
        token = self._peek()
        if token is None:
            raise MetricValidationError("The definition ends unexpectedly.")
        self.i += 1
        return token

    def _is_op(self, value: str, offset: int = 0) -> bool:
        token = self._peek(offset)
        return token is not None and token.kind == "op" and token.value == value

    def _is_kw(self, word: str, offset: int = 0) -> bool:
        token = self._peek(offset)
        return token is not None and token.kind == "ident" and token.value.upper() == word

    def _expect_op(self, value: str) -> None:
        token = self._next()
        if token.kind != "op" or token.value != value:
            raise MetricValidationError(f"Expected '{value}' but found {token.value!r}.")

    def _expect_kw(self, word: str) -> None:
        token = self._next()
        if token.kind != "ident" or token.value.upper() != word:
            raise MetricValidationError(f"Expected {word} but found {token.value!r}.")

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise MetricValidationError("The definition is nested too deeply.")

    def _leave(self) -> None:
        self.depth -= 1

    def _finish(self) -> None:
        extra = self._peek()
        if extra is not None:
            raise MetricValidationError(f"Unexpected {extra.value!r} at position {extra.pos}.")

    def _column(self, token: _Token) -> tuple[str, str]:
        if token.kind != "ident" or token.value.upper() in KEYWORDS:
            raise MetricValidationError(f"Expected a column name but found {token.value!r}.")
        real = self._lower.get(token.value.lower())
        if real is None:
            shown = token.value[:40]
            available = ", ".join(sorted(self.columns)[:30])
            raise MetricValidationError(f"Unknown column '{shown}'. Available columns: {available}.")
        self.columns_used.add(real)
        return real, self.columns[real]

    @staticmethod
    def _number_sql(token: _Token) -> str:
        if len(token.value) > MAX_NUMBER_CHARS:
            raise MetricValidationError("Number literal is too long.")
        return token.value

    # ---------- metric expression: aggregates + arithmetic ----------
    def parse_metric(self) -> str:
        sql, has_aggregate = self._sum_expr()
        self._finish()
        if not has_aggregate:
            raise MetricValidationError(
                "A metric must use an aggregate: SUM, AVG, MIN, MAX or COUNT."
            )
        return sql

    def _sum_expr(self) -> tuple[str, bool]:
        left, has_agg = self._prod_expr()
        while self._is_op("+") or self._is_op("-"):
            op = self._next().value
            right, right_agg = self._prod_expr()
            left = f"({left} {op} {right})"
            has_agg = has_agg or right_agg
        return left, has_agg

    def _prod_expr(self) -> tuple[str, bool]:
        left, has_agg = self._unary_expr()
        while self._is_op("*") or self._is_op("/"):
            op = self._next().value
            right, right_agg = self._unary_expr()
            if op == "/":
                # Integer division truncates in Postgres and /0 raises an error.
                # Every division is rewritten to a float division guarded by NULLIF.
                left = f"(CAST({left} AS DOUBLE PRECISION) / NULLIF({right}, 0))"
            else:
                left = f"({left} * {right})"
            has_agg = has_agg or right_agg
        return left, has_agg

    def _unary_expr(self) -> tuple[str, bool]:
        if self._is_op("-"):
            self._next()
            self._enter()
            sql, has_agg = self._unary_expr()
            self._leave()
            return f"(-{sql})", has_agg
        return self._primary_expr()

    def _primary_expr(self) -> tuple[str, bool]:
        token = self._next()
        if token.kind == "number":
            return self._number_sql(token), False
        if token.kind == "op" and token.value == "(":
            self._enter()
            sql, has_agg = self._sum_expr()
            self._expect_op(")")
            self._leave()
            return f"({sql})", has_agg
        if token.kind == "ident":
            name = token.value.upper()
            if name in AGGREGATES and self._is_op("("):
                return self._aggregate(name), True
            if token.value.lower() in self._lower:
                raise MetricValidationError(
                    f"Column '{token.value[:40]}' must be inside an aggregate, e.g. SUM({token.value[:40]})."
                )
            raise MetricValidationError(
                f"Unknown function '{token.value[:40]}'. Allowed: SUM, AVG, MIN, MAX, COUNT."
            )
        raise MetricValidationError(f"Unexpected {token.value!r} at position {token.pos}.")

    def _aggregate(self, func: str) -> str:
        self._expect_op("(")
        self.aggregates_used.add(func)

        if func == "COUNT":
            if self._is_op("*"):
                self._next()
                self._expect_op(")")
                return "COUNT(*)"
            distinct = False
            if self._is_kw("DISTINCT"):
                self._next()
                distinct = True
            token = self._next()
            if self._is_op("("):
                raise MetricValidationError("Nested functions are not allowed inside COUNT.")
            real, _dtype = self._column(token)
            self._expect_op(")")
            return f"COUNT(DISTINCT {_quote_ident(real)})" if distinct else f"COUNT({_quote_ident(real)})"

        if self._is_kw("DISTINCT"):
            raise MetricValidationError("DISTINCT is only supported inside COUNT.")

        start = self.i
        self._arg_cols = []
        arg_sql = self._arg_sum()
        single = self.i - start == 1 and self.tokens[start].kind == "ident"
        self._expect_op(")")

        if not self._arg_cols:
            raise MetricValidationError(f"{func}() needs at least one column.")
        dtypes = {self.columns[real] for real in self._arg_cols}
        if func in {"MIN", "MAX"} and single and dtypes == {"datetime"}:
            pass
        elif not dtypes <= NUMERIC_TYPES:
            bad = sorted(dtypes - NUMERIC_TYPES)
            raise MetricValidationError(
                f"{func}() requires numeric columns, found type {', '.join(bad)}."
            )
        return f"{func}({arg_sql})"

    # arithmetic inside an aggregate: columns, numbers, + - *   (no division, no functions)
    def _arg_sum(self) -> str:
        left = self._arg_prod()
        while self._is_op("+") or self._is_op("-"):
            op = self._next().value
            right = self._arg_prod()
            left = f"({left} {op} {right})"
        return left

    def _arg_prod(self) -> str:
        left = self._arg_unary()
        while self._is_op("*") or self._is_op("/"):
            op = self._next().value
            if op == "/":
                raise MetricValidationError(
                    "Division inside an aggregate is not allowed. Divide aggregates instead, "
                    "e.g. SUM(a) / SUM(b)."
                )
            right = self._arg_unary()
            left = f"({left} * {right})"
        return left

    def _arg_unary(self) -> str:
        if self._is_op("-"):
            self._next()
            self._enter()
            sql = self._arg_unary()
            self._leave()
            return f"(-{sql})"
        token = self._next()
        if token.kind == "number":
            return self._number_sql(token)
        if token.kind == "op" and token.value == "(":
            self._enter()
            sql = self._arg_sum()
            self._expect_op(")")
            self._leave()
            return f"({sql})"
        if token.kind == "ident":
            if self._is_op("("):
                raise MetricValidationError("Nested functions are not allowed inside an aggregate.")
            real, _dtype = self._column(token)
            self._arg_cols.append(real)
            return _quote_ident(real)
        raise MetricValidationError(f"Unexpected {token.value!r} at position {token.pos}.")

    # ---------- filter: boolean conditions ----------
    def parse_filter(self) -> str:
        sql = self._or()
        self._finish()
        return sql

    def _or(self) -> str:
        parts = [self._and()]
        while self._is_kw("OR"):
            self._next()
            parts.append(self._and())
        return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"

    def _and(self) -> str:
        parts = [self._not()]
        while self._is_kw("AND"):
            self._next()
            parts.append(self._not())
        return parts[0] if len(parts) == 1 else "(" + " AND ".join(parts) + ")"

    def _not(self) -> str:
        if self._is_kw("NOT"):
            self._next()
            self._enter()
            sql = self._not()
            self._leave()
            return f"(NOT {sql})"
        if self._is_op("("):
            self._next()
            self._enter()
            sql = self._or()
            self._expect_op(")")
            self._leave()
            return sql
        return self._predicate()

    def _literal(self, dtype: str, column: str) -> str:
        negative = False
        if self._is_op("-"):
            self._next()
            negative = True
        token = self._next()

        if dtype in NUMERIC_TYPES:
            if token.kind != "number":
                raise MetricValidationError(f"Column '{column}' is numeric; compare it to a number.")
            return ("-" if negative else "") + self._number_sql(token)

        if negative or token.kind != "string":
            raise MetricValidationError(f"Column '{column}' needs a quoted value like 'abc'.")
        value = token.value[1:-1].replace("''", "'")
        if len(value) > 200:
            raise MetricValidationError("String value is too long.")
        if dtype == "datetime":
            try:
                datetime.fromisoformat(value)
            except ValueError:
                raise MetricValidationError(
                    f"'{value[:30]}' is not a valid date. Use ISO format like '2026-01-31'."
                ) from None
            return f"CAST({_quote_string(value)} AS TIMESTAMP)"
        return _quote_string(value)

    def _predicate(self) -> str:
        column, dtype = self._column(self._next())
        if dtype not in NUMERIC_TYPES | {"text", "datetime"}:
            raise MetricValidationError(f"Column '{column}' has type '{dtype}', which filters do not support yet.")
        col_sql = _quote_ident(column)
        token = self._next()

        if token.kind == "op" and token.value in COMPARISONS:
            op = "<>" if token.value == "!=" else token.value
            if dtype == "text" and token.value not in EQUALITY_ONLY:
                raise MetricValidationError(f"Text column '{column}' only supports =, != and <>.")
            return f"{col_sql} {op} {self._literal(dtype, column)}"

        upper = token.value.upper() if token.kind == "ident" else ""

        if upper == "IS":
            negate = False
            if self._is_kw("NOT"):
                self._next()
                negate = True
            self._expect_kw("NULL")
            return f"{col_sql} IS {'NOT ' if negate else ''}NULL"

        negate = False
        if upper == "NOT":
            negate = True
            token = self._next()
            upper = token.value.upper() if token.kind == "ident" else ""

        if upper == "IN":
            self._expect_op("(")
            items = [self._literal(dtype, column)]
            while self._is_op(","):
                self._next()
                items.append(self._literal(dtype, column))
                if len(items) > MAX_IN_ITEMS:
                    raise MetricValidationError(f"IN lists are limited to {MAX_IN_ITEMS} values.")
            self._expect_op(")")
            return f"{col_sql} {'NOT ' if negate else ''}IN ({', '.join(items)})"

        if upper == "LIKE":
            if dtype != "text":
                raise MetricValidationError(f"LIKE only works on text columns, '{column}' is {dtype}.")
            return f"{col_sql} {'NOT ' if negate else ''}LIKE {self._literal(dtype, column)}"

        if upper == "BETWEEN" and not negate:
            if dtype == "text":
                raise MetricValidationError(f"BETWEEN is not supported on text column '{column}'.")
            low = self._literal(dtype, column)
            self._expect_kw("AND")
            high = self._literal(dtype, column)
            return f"({col_sql} BETWEEN {low} AND {high})"

        raise MetricValidationError(
            f"Expected a comparison (=, <, IN, LIKE, BETWEEN, IS NULL) after '{column}'."
        )


def validate_metric(
    expression: str,
    filter_sql: str | None,
    columns: Mapping[str, str],
) -> ValidatedMetric:
    """
    columns maps real column name -> profiled dtype (integer, float, text, datetime).
    Returns canonical, safe-to-store SQL, or raises MetricValidationError.
    """
    if not expression or not expression.strip():
        raise MetricValidationError("An expression is required.")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise MetricValidationError(f"Expression is longer than {MAX_EXPRESSION_CHARS} characters.")

    parser = _Parser(_tokenize(expression), columns)
    expression_sql = parser.parse_metric()
    columns_used = set(parser.columns_used)
    aggregates_used = set(parser.aggregates_used)

    canonical_filter: str | None = None
    if filter_sql and filter_sql.strip():
        if len(filter_sql) > MAX_FILTER_CHARS:
            raise MetricValidationError(f"Filter is longer than {MAX_FILTER_CHARS} characters.")
        filter_parser = _Parser(_tokenize(filter_sql), columns)
        canonical_filter = filter_parser.parse_filter()
        columns_used |= filter_parser.columns_used

    return ValidatedMetric(
        expression_sql=expression_sql,
        filter_sql=canonical_filter,
        columns_used=tuple(sorted(columns_used)),
        aggregates_used=tuple(sorted(aggregates_used)),
    )