from alembic import op
import sqlalchemy as sa

revision = '0007_patch_suggestions'
down_revision = '0006_pr_comments'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('patch_suggestions', sa.Column('id', sa.String(36), primary_key=True), sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id')), sa.Column('repository_id', sa.String(36), sa.ForeignKey('repositories.id')), sa.Column('analysis_id', sa.String(36), sa.ForeignKey('analyses.id'), nullable=False), sa.Column('provider', sa.String(80), nullable=False), sa.Column('model', sa.String(120), nullable=False), sa.Column('status', sa.String(30), nullable=False), sa.Column('unified_diff', sa.Text(), nullable=False), sa.Column('explanation', sa.Text(), nullable=False), sa.Column('confidence', sa.Float(), nullable=False), sa.Column('risk_level', sa.String(20), nullable=False), sa.Column('affected_files', sa.Text(), nullable=False), sa.Column('validation_errors', sa.Text(), nullable=False), sa.Column('source_context_fingerprint', sa.String(64), nullable=False), sa.Column('created_by_user_id', sa.String(36), sa.ForeignKey('users.id')), sa.Column('created_at', sa.DateTime(timezone=True)), sa.Column('updated_at', sa.DateTime(timezone=True)))
    op.create_table('patch_decisions', sa.Column('id', sa.String(36), primary_key=True), sa.Column('patch_id', sa.String(36), sa.ForeignKey('patch_suggestions.id'), nullable=False), sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False), sa.Column('decision', sa.String(20), nullable=False), sa.Column('feedback', sa.Text()), sa.Column('created_at', sa.DateTime(timezone=True)))
    for table, column in [('patch_suggestions','organization_id'),('patch_suggestions','repository_id'),('patch_suggestions','analysis_id'),('patch_suggestions','status'),('patch_decisions','patch_id'),('patch_decisions','user_id')]: op.create_index(f'ix_{table}_{column}', table, [column])

def downgrade():
    for name in ('ix_patch_decisions_user_id','ix_patch_decisions_patch_id','ix_patch_suggestions_status','ix_patch_suggestions_analysis_id','ix_patch_suggestions_repository_id','ix_patch_suggestions_organization_id'): op.drop_index(name, table_name=name.split('_', 3)[1] + '_' + name.split('_', 3)[2] if False else ('patch_decisions' if 'decisions' in name else 'patch_suggestions'))
    op.drop_table('patch_decisions'); op.drop_table('patch_suggestions')