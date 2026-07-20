"""add issue status

Revision ID: c3d5a9287e14
Revises: b7c4f13a91d2
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d5a9287e14'
down_revision: Union[str, Sequence[str], None] = 'b7c4f13a91d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'issues',
        sa.Column(
            'status',
            sa.String(length=20),
            nullable=False,
            server_default='OPEN',
        ),
    )
    op.create_check_constraint(
        'ck_issues_status',
        'issues',
        "status IN ('OPEN', 'RESOLVED', 'IGNORED')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_issues_status', 'issues', type_='check')
    op.drop_column('issues', 'status')
