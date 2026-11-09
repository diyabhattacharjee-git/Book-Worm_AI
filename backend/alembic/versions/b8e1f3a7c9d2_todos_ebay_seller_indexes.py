"""to-do list, eBay seller tools, query indexes

Revision ID: b8e1f3a7c9d2
Revises: 7c2d4e9a1b30
Create Date: 2026-11-09 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e1f3a7c9d2'
down_revision: Union[str, Sequence[str], None] = '7c2d4e9a1b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('reading_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('normalized_title', sa.String(length=200), nullable=False),
    sa.Column('notes', sa.String(length=1000), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('completed', sa.Boolean(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    *_timestamps(),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_reading_tasks_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reading_tasks'))
    )
    op.create_index(op.f('ix_reading_tasks_user_id'), 'reading_tasks', ['user_id'], unique=False)
    op.create_index('uq_reading_tasks_open_title', 'reading_tasks', ['user_id', 'normalized_title'], unique=True,
                    postgresql_where=sa.text('NOT completed'), sqlite_where=sa.text('NOT completed'))

    op.create_table('ebay_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('environment', sa.String(length=12), nullable=False),
    sa.Column('refresh_token_encrypted', sa.Text(), nullable=False),
    sa.Column('refresh_token_expires_at', sa.DateTime(timezone=True), nullable=True),
    *_timestamps(),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ebay_accounts_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ebay_accounts')),
    sa.UniqueConstraint('user_id', name=op.f('uq_ebay_accounts_user_id'))
    )

    op.create_table('ebay_publications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('listing_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('sku', sa.String(length=50), nullable=False),
    sa.Column('offer_id', sa.String(length=40), nullable=True),
    sa.Column('ebay_listing_id', sa.String(length=40), nullable=True),
    sa.Column('url', sa.String(length=300), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('price_amount', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    *_timestamps(),
    sa.ForeignKeyConstraint(['listing_id'], ['marketplace_listings.id'], name=op.f('fk_ebay_publications_listing_id_marketplace_listings'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ebay_publications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ebay_publications')),
    sa.UniqueConstraint('listing_id', name=op.f('uq_ebay_publications_listing_id'))
    )
    op.create_index(op.f('ix_ebay_publications_status'), 'ebay_publications', ['status'], unique=False)
    op.create_index(op.f('ix_ebay_publications_user_id'), 'ebay_publications', ['user_id'], unique=False)

    op.create_index('ix_reviews_book_status', 'reviews', ['book_id', 'status'], unique=False)
    op.create_index('ix_search_queries_user_created', 'search_queries', ['user_id', 'created_at'], unique=False)
    op.create_index('ix_listing_seller_status', 'marketplace_listings', ['seller_id', 'status'], unique=False)
    op.create_index('ix_listing_book_status', 'marketplace_listings', ['book_id', 'status'], unique=False)
    op.create_index('ix_conversations_user_updated', 'conversations', ['user_id', 'updated_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_conversations_user_updated', table_name='conversations')
    op.drop_index('ix_listing_book_status', table_name='marketplace_listings')
    op.drop_index('ix_listing_seller_status', table_name='marketplace_listings')
    op.drop_index('ix_search_queries_user_created', table_name='search_queries')
    op.drop_index('ix_reviews_book_status', table_name='reviews')
    op.drop_index(op.f('ix_ebay_publications_user_id'), table_name='ebay_publications')
    op.drop_index(op.f('ix_ebay_publications_status'), table_name='ebay_publications')
    op.drop_table('ebay_publications')
    op.drop_table('ebay_accounts')
    op.drop_index('uq_reading_tasks_open_title', table_name='reading_tasks',
                  postgresql_where=sa.text('NOT completed'), sqlite_where=sa.text('NOT completed'))
    op.drop_index(op.f('ix_reading_tasks_user_id'), table_name='reading_tasks')
    op.drop_table('reading_tasks')
