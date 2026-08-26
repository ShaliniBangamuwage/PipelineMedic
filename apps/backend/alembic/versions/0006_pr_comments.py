from alembic import op
import sqlalchemy as sa

revision = '0006_pr_comments'
down_revision = '0005_worker_queue'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('repositories') as batch:
        batch.add_column(sa.Column('pr_comments_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('pr_comment_min_confidence', sa.Float(), nullable=False, server_default='0.8'))
        batch.add_column(sa.Column('pr_comment_allowed_branches', sa.Text(), nullable=False, server_default='main'))
        batch.add_column(sa.Column('pr_comment_include_similar_incident', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column('pr_comment_include_patch', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('pr_comment_deliveries',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id')),
        sa.Column('repository_id', sa.String(36), sa.ForeignKey('repositories.id'), nullable=False), sa.Column('analysis_id', sa.String(36), sa.ForeignKey('analyses.id'), nullable=False),
        sa.Column('workflow_run_id', sa.String(80)), sa.Column('pull_request_number', sa.Integer()), sa.Column('github_comment_id', sa.String(80)), sa.Column('github_comment_url', sa.String(500)),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('attempt_count', sa.Integer(), nullable=False), sa.Column('last_error_code', sa.String(40)), sa.Column('last_error_message', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True)), sa.Column('updated_at', sa.DateTime(timezone=True)), sa.Column('delivered_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('repository_id', 'analysis_id', name='uq_pr_comment_analysis'))
    op.create_index('ix_pr_comment_deliveries_organization_id', 'pr_comment_deliveries', ['organization_id'])
    op.create_index('ix_pr_comment_deliveries_repository_id', 'pr_comment_deliveries', ['repository_id'])
    op.create_index('ix_pr_comment_deliveries_analysis_id', 'pr_comment_deliveries', ['analysis_id'])
    op.create_index('ix_pr_comment_deliveries_status', 'pr_comment_deliveries', ['status'])

def downgrade():
    for name in ('ix_pr_comment_deliveries_status','ix_pr_comment_deliveries_analysis_id','ix_pr_comment_deliveries_repository_id','ix_pr_comment_deliveries_organization_id'):
        op.drop_index(name, table_name='pr_comment_deliveries')
    op.drop_table('pr_comment_deliveries')
    with op.batch_alter_table('repositories') as batch:
        for name in ('pr_comment_include_patch','pr_comment_include_similar_incident','pr_comment_allowed_branches','pr_comment_min_confidence','pr_comments_enabled'):
            batch.drop_column(name)