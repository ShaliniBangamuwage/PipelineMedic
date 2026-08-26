from alembic import op
import sqlalchemy as sa
revision='0001_initial'
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('repositories',sa.Column('id',sa.String(36),primary_key=True),sa.Column('owner',sa.String(100),nullable=False),sa.Column('name',sa.String(100),nullable=False),sa.Column('default_branch',sa.String(100),nullable=False),sa.Column('active',sa.Boolean(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True)),sa.Column('updated_at',sa.DateTime(timezone=True)),sa.UniqueConstraint('owner','name',name='uq_repository_owner_name'))
    op.create_table('analyses',sa.Column('id',sa.String(36),primary_key=True),sa.Column('repository_id',sa.String(36),sa.ForeignKey('repositories.id')),sa.Column('workflow_name',sa.String(200),nullable=False),sa.Column('branch',sa.String(200),nullable=False),sa.Column('commit_sha',sa.String(100),nullable=False),sa.Column('source',sa.String(20),nullable=False),sa.Column('category',sa.String(50),nullable=False),sa.Column('summary',sa.String(500),nullable=False),sa.Column('root_cause',sa.Text(),nullable=False),sa.Column('failed_step',sa.String(200),nullable=False),sa.Column('confidence',sa.Float(),nullable=False),sa.Column('severity',sa.String(20),nullable=False),sa.Column('cleaned_log',sa.Text(),nullable=False),sa.Column('raw_log_excerpt',sa.Text(),nullable=False),sa.Column('resolved',sa.Boolean(),nullable=False),sa.Column('actual_solution',sa.Text()),sa.Column('created_at',sa.DateTime(timezone=True)),sa.Column('updated_at',sa.DateTime(timezone=True)))
    op.create_table('incident_feedback',sa.Column('id',sa.String(36),primary_key=True),sa.Column('analysis_id',sa.String(36),sa.ForeignKey('analyses.id'),nullable=False),sa.Column('accurate',sa.Boolean(),nullable=False),sa.Column('actual_category',sa.String(50)),sa.Column('actual_solution',sa.Text()),sa.Column('submitted_at',sa.DateTime(timezone=True)))
    for name,table,column in [('ix_analyses_category','analyses','category'),('ix_analyses_repository_id','analyses','repository_id'),('ix_analyses_branch','analyses','branch'),('ix_analyses_resolved','analyses','resolved'),('ix_analyses_created_at','analyses','created_at')]: op.create_index(name,table,[column])
def downgrade():
    for name in ['ix_analyses_created_at','ix_analyses_resolved','ix_analyses_branch','ix_analyses_repository_id','ix_analyses_category']: op.drop_index(name,table_name='analyses')
    op.drop_table('incident_feedback'); op.drop_table('analyses'); op.drop_table('repositories')
