"""add goal column to pref

Revision ID: b1c2d3e4f5g6
Revises: a1b2c3d4e5f6
Create Date: 2025-11-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5g6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add goal column to pref table."""
    # Add goal column with default value 4.0. DEfault value is minimum goal by game rules.
    # It is needed to reparse all xlm files to set actual goals.
    op.add_column('pref', sa.Column('goal', sa.Numeric(precision=10, scale=2), nullable=False, server_default='4.0'))

    # Remove the server default after adding the column (so new inserts require explicit values)
    op.alter_column('pref', 'goal', server_default=None)


def downgrade() -> None:
    """Remove goal column from pref table."""
    op.drop_column('pref', 'goal')

