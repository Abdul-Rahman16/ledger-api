import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from core.db import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=True)  # NULL = anonymous guest dataset
    name = Column(String, nullable=False)
    source_type = Column(String, nullable=False)  # csv, excel, json
    original_filename = Column(String, nullable=False)
    storage_key = Column(String, nullable=True)  # object-store key of the raw upload
    table_name = Column(String, nullable=True)  # physical table holding the cleaned data
    status = Column(String, nullable=False, default="uploaded")  # uploaded, profiled, ready, failed
    row_count = Column(Integer, nullable=True)
    column_count = Column(Integer, nullable=True)
    quality_score = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_datasets_user_id", "user_id"),
        Index("ix_datasets_status", "status"),
    )


class DatasetColumn(Base):
    __tablename__ = "dataset_columns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False)
    name = Column(String, nullable=False)
    position = Column(Integer, nullable=False)
    dtype = Column(String, nullable=False)
    null_pct = Column(Float, nullable=False, default=0.0)
    unique_count = Column(Integer, nullable=True)
    stats = Column(JSON, nullable=True)  # min/max/mean/top values, depending on dtype

    __table_args__ = (
        UniqueConstraint("dataset_id", "name", name="uq_dataset_column_name"),
        Index("ix_dataset_columns_dataset_id", "dataset_id"),
    )


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    sql_expression = Column(Text, nullable=False)  # e.g. SUM(order_total)
    filter_sql = Column(Text, nullable=True)  # e.g. status = 'completed'
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("dataset_id", "name", "version", name="uq_metric_version"),
        Index("ix_metric_lookup", "dataset_id", "name", "is_active"),
    )


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(UUID(as_uuid=True), ForeignKey("datasets.id"), nullable=False)
    user_id = Column(String, nullable=True)
    question = Column(Text, nullable=False)
    matched_metric_id = Column(UUID(as_uuid=True), ForeignKey("metric_definitions.id"), nullable=True)
    generated_sql = Column(Text, nullable=True)
    status = Column(String, nullable=False)  # answered, rejected, failed
    rejection_reason = Column(Text, nullable=True)
    row_count = Column(Integer, nullable=True)
    tokens_used = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_query_logs_dataset_id", "dataset_id"),
        Index("ix_query_logs_user_id", "user_id"),
    )