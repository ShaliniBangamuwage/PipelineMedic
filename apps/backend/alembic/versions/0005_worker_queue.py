from alembic import op
import sqlalchemy as sa

revision = '0005_worker_queue'
down_revision = '0004_jobs'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('jobs', sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column('jobs', 'next_retry_at')