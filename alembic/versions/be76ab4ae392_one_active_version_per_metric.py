"""one active version per metric

Revision ID: be76ab4ae392
Revises: cf7e164f27d4
Create Date: 2026-10-28 18:40:04.638262

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'be76ab4ae392'
down_revision: Union[str, Sequence[str], None] = 'cf7e164f27d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'uq_metric_one_active',
        'metric_definitions',
        ['dataset_id', 'name'],
        unique=True,
        postgresql_where=sa.text('is_active'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'uq_metric_one_active',
        table_name='metric_definitions',
        postgresql_where=sa.text('is_active'),
    )