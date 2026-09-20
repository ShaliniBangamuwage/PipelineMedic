from alembic import op
import sqlalchemy as sa

revision = '0011_analysis_failed_command'
down_revision = '0010_analysis_workflow_identity'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('analyses', sa.Column('failed_command', sa.String(500), nullable=True))

def downgrade():
    op.drop_column('analyses', 'failed_command')