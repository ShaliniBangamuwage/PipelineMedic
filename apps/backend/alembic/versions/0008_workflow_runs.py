from alembic import op
import sqlalchemy as sa

revision = '0008_workflow_runs'
down_revision = '0007_patch_suggestions'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('workflow_runs', sa.Column('id', sa.String(36), primary_key=True), sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id')), sa.Column('repository_id', sa.String(36), sa.ForeignKey('repositories.id'), nullable=False), sa.Column('github_run_id', sa.String(80), nullable=False), sa.Column('github_run_url', sa.String(500), nullable=False), sa.Column('workflow_name', sa.String(200), nullable=False), sa.Column('branch', sa.String(100), nullable=False), sa.Column('head_sha', sa.String(100), nullable=False), sa.Column('status', sa.String(20), nullable=False), sa.Column('conclusion', sa.String(20), nullable=False), sa.Column('raw_payload', sa.Text(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True)), sa.Column('updated_at', sa.DateTime(timezone=True)), sa.UniqueConstraint('repository_id', 'github_run_id', name='uq_workflow_run_github_id'))
    op.create_index('ix_workflow_runs_organization_id', 'workflow_runs', ['organization_id'])
    op.create_index('ix_workflow_runs_repository_id', 'workflow_runs', ['repository_id'])
    op.create_index('ix_workflow_runs_github_run_id', 'workflow_runs', ['github_run_id'])
    op.create_index('ix_workflow_runs_status', 'workflow_runs', ['status'])
    op.create_index('ix_workflow_runs_conclusion', 'workflow_runs', ['conclusion'])
    op.create_index('ix_workflow_runs_created_at', 'workflow_runs', ['created_at'])

def downgrade():
    op.drop_index('ix_workflow_runs_created_at', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_conclusion', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_status', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_github_run_id', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_repository_id', table_name='workflow_runs')
    op.drop_index('ix_workflow_runs_organization_id', table_name='workflow_runs')
    op.drop_table('workflow_runs')
