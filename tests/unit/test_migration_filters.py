from types import SimpleNamespace

from core.migration_filters import include_object

DATA_TABLE = "ds_" + "a" * 32


def check(name, type_, obj=None, reflected=True):
    return include_object(obj or SimpleNamespace(), name, type_, reflected, None)


def test_runtime_dataset_tables_are_ignored_by_autogenerate():
    assert check(DATA_TABLE, "table") is False


def test_indexes_and_columns_of_dataset_tables_are_ignored():
    owner = SimpleNamespace(table=SimpleNamespace(name=DATA_TABLE))
    assert check("ix_something", "index", owner) is False
    assert check("amount", "column", owner) is False


def test_application_tables_are_still_managed():
    for name in ("datasets", "dataset_columns", "metric_definitions", "query_logs", "alembic_version"):
        assert check(name, "table") is True
    owner = SimpleNamespace(table=SimpleNamespace(name="metric_definitions"))
    assert check("uq_metric_one_active", "index", owner) is True
    assert check("version", "column", owner) is True