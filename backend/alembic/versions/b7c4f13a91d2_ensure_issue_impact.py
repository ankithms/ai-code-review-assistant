"""ensure issue impact

Revision ID: b7c4f13a91d2
Revises: 9c0a7e65f2b1
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7c4f13a91d2'
down_revision: Union[str, Sequence[str], None] = '9c0a7e65f2b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE issues ADD COLUMN IF NOT EXISTS impact TEXT")
    op.execute("ALTER TABLE issues DROP COLUMN IF EXISTS confidence")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE issues ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION")
    op.execute("ALTER TABLE issues DROP COLUMN IF EXISTS impact")
