"""service ticket approval signature

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04 19:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('service_tickets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('approval_signature', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('approval_signed_by', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('service_tickets', schema=None) as batch_op:
        batch_op.drop_column('approval_signed_by')
        batch_op.drop_column('approval_signature')
