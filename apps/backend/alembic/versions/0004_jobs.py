from alembic import op
import sqlalchemy as sa
revision='0004_jobs'; down_revision='0003_embeddings'; branch_labels=None; depends_on=None
def upgrade():
    op.create_table('jobs',sa.Column('id',sa.String(36),primary_key=True),sa.Column('organization_id',sa.String(36),sa.ForeignKey('organizations.id')),sa.Column('kind',sa.String(80),nullable=False),sa.Column('status',sa.String(20),nullable=False),sa.Column('delivery_id',sa.String(200),unique=True),sa.Column('workflow_run_id',sa.String(80)),sa.Column('attempts',sa.Integer(),nullable=False),sa.Column('error_message',sa.Text()),sa.Column('created_at',sa.DateTime(timezone=True)),sa.Column('updated_at',sa.DateTime(timezone=True)))
    op.create_index('ix_jobs_organization_id','jobs',['organization_id']);op.create_index('ix_jobs_status','jobs',['status']);op.create_index('ix_jobs_delivery_id','jobs',['delivery_id'],unique=True);op.create_index('ix_jobs_workflow_run_id','jobs',['workflow_run_id'])
def downgrade():
    for name in ['ix_jobs_workflow_run_id','ix_jobs_delivery_id','ix_jobs_status','ix_jobs_organization_id']:op.drop_index(name,table_name='jobs')
    op.drop_table('jobs')