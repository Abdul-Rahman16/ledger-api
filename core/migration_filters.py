"""
Alembic autogenerate filter.

Dataset data tables (ds_<uuid>) are created at runtime by ingestion. They are not part
of the SQLAlchemy models, so without this filter `alembic revision --autogenerate`
would treat them as leftovers and emit op.drop_table() for every uploaded dataset.
"""

DATASET_TABLE_PREFIX = "ds_"


def include_object(object, name, type_, reflected, compare_to):  # noqa: A002 (Alembic's signature)
    if type_ == "table" and name and name.startswith(DATASET_TABLE_PREFIX):
        return False
    table = getattr(object, "table", None)  # indexes, constraints and columns point at their table
    table_name = getattr(table, "name", None)
    if table_name and table_name.startswith(DATASET_TABLE_PREFIX):
        return False
    return True