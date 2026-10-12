"""stored images

Revision ID: 7c2d4e9a1b30
Revises: e5370b6b20b9
Create Date: 2026-10-12 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c2d4e9a1b30'
down_revision: Union[str, Sequence[str], None] = 'e5370b6b20b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('stored_images',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('content_type', sa.String(length=32), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stored_images')),
    sa.UniqueConstraint('key', name=op.f('uq_stored_images_key'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('stored_images')
