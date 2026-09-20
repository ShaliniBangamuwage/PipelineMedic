from alembic import op
import sqlalchemy as sa

revision = '0009_workflow_run_attempts'
down_revision = '0008_workflow_runs'
branch_labels = None
depends_on = None

def upgrade():
    op.drop_constraint('uq_workflow_run_github_id', 'workflow_runs', type_='unique')
    op.add_column('workflow_runs', sa.Column('run_attempt', sa.Integer(), nullable=True))
    op.add_column('jobs', sa.Column('run_attempt', sa.Integer(), nullable=True))
    op.create_unique_constraint('uq_workflow_run_github_attempt', 'workflow_runs', ['repository_id', 'github_run_id', 'run_attempt'])
    op.create_index('ix_workflow_runs_run_attempt', 'workflow_runs', ['run_attempt'])
    op.create_index('ix_jobs_run_attempt', 'jobs', ['run_attempt'])

def downgrade():
    op.drop_constraint('uq_workflow_run_github_attempt', 'workflow_runs', type_='unique')
    op.drop_index('ix_jobs_run_attempt', table_name='jobs')
    op.drop_index('ix_workflow_runs_run_attempt', table_name='workflow_runs')
    op.drop_column('jobs', 'run_attempt')
    op.drop_column('workflow_runs', 'run_attempt')
    op.create_unique_constraint('uq_workflow_run_github_id', 'workflow_runs', ['repository_id', 'github_run_id'])