from alembic import op
import sqlalchemy as sa

revision = '0010_analysis_workflow_identity'
down_revision = '0009_workflow_run_attempts'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('analyses', sa.Column('workflow_run_id', sa.String(80), nullable=True))
    op.add_column('analyses', sa.Column('run_attempt', sa.Integer(), nullable=True))
    op.create_index('ix_analyses_workflow_run_id', 'analyses', ['workflow_run_id'])
    op.create_index('ix_analyses_run_attempt', 'analyses', ['run_attempt'])

def downgrade():
    op.drop_index('ix_analyses_run_attempt', table_name='analyses')
    op.drop_index('ix_analyses_workflow_run_id', table_name='analyses')
    op.drop_column('analyses', 'run_attempt')
    op.drop_column('analyses', 'workflow_run_id')