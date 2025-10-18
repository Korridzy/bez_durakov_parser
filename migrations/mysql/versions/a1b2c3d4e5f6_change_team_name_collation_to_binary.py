"""change team_name collation to binary

Revision ID: a1b2c3d4e5f6
Revises: 50068160f559
Create Date: 2025-10-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '50068160f559'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change team_name column collation to binary for exact character matching."""
    # Use Alembic's alter_column for better portability
    # utf8mb4_bin ensures 'đ' and 'd' are treated as different characters
    op.alter_column(
        'teams',
        'team_name',
        existing_type=sa.String(256),
        type_=sa.String(256),
        nullable=False,
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_bin'
    )


def downgrade() -> None:
    """Revert team_name column collation to database default."""
    # Dynamically determine the database default charset and collation for portability
    # across MySQL versions (5.7 uses utf8mb4_general_ci, 8+ uses utf8mb4_0900_ai_ci)
    # and different database configurations
    from sqlalchemy import text

    conn = op.get_bind()

    # Get both charset and collation to ensure they match
    result = conn.execute(text("SELECT @@character_set_database, @@collation_database")).fetchone()

    if result:
        db_charset = result[0]
        db_collation = result[1]
    else:
        # Fallback to utf8mb4 defaults if query fails
        db_charset = 'utf8mb4'
        db_collation = 'utf8mb4_general_ci'

    # Use Alembic's alter_column with dynamically determined charset and collation
    op.alter_column(
        'teams',
        'team_name',
        existing_type=sa.String(256),
        type_=sa.String(256),
        nullable=False,
        mysql_charset=db_charset,
        mysql_collate=db_collation
    )
