"""add repositories table

Revision ID: d4a62cf5b8e9
Revises: c3d5a9287e14
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a62cf5b8e9'
down_revision: Union[str, Sequence[str], None] = 'c3d5a9287e14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'repositories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('full_name'),
    )
    op.create_index(
        op.f('ix_repositories_full_name'),
        'repositories',
        ['full_name'],
        unique=True,
    )
    op.add_column(
        'pull_requests',
        sa.Column('repository_id', sa.Integer(), nullable=True),
    )
    op.execute(
        """
        INSERT INTO repositories (full_name)
        SELECT DISTINCT repository
        FROM pull_requests
        WHERE repository IS NOT NULL
        ON CONFLICT (full_name) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE pull_requests
        SET repository_id = repositories.id
        FROM repositories
        WHERE pull_requests.repository = repositories.full_name
        """
    )
    op.create_index(
        op.f('ix_pull_requests_repository_id'),
        'pull_requests',
        ['repository_id'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_pull_requests_repository_id_repositories',
        'pull_requests',
        'repositories',
        ['repository_id'],
        ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_pull_requests_repository_id_repositories',
        'pull_requests',
        type_='foreignkey',
    )
    op.drop_index(op.f('ix_pull_requests_repository_id'), table_name='pull_requests')
    op.drop_column('pull_requests', 'repository_id')
    op.drop_index(op.f('ix_repositories_full_name'), table_name='repositories')
    op.drop_table('repositories')
