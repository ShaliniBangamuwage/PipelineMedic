from alembic import op
import sqlalchemy as sa
revision='0003_embeddings'; down_revision='0002_auth_tenancy'; branch_labels=None; depends_on=None
def upgrade():
    op.create_table('incident_embeddings',sa.Column('id',sa.String(36),primary_key=True),sa.Column('analysis_id',sa.String(36),sa.ForeignKey('analyses.id'),unique=True,nullable=False),sa.Column('organization_id',sa.String(36),sa.ForeignKey('organizations.id')),sa.Column('content_fingerprint',sa.String(64),nullable=False),sa.Column('vector_json',sa.Text(),nullable=False),sa.Column('provider',sa.String(80),nullable=False),sa.Column('model',sa.String(120),nullable=False),sa.Column('dimensions',sa.Integer(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True)))
    op.create_index('ix_incident_embeddings_analysis_id','incident_embeddings',['analysis_id'],unique=True);op.create_index('ix_incident_embeddings_organization_id','incident_embeddings',['organization_id']);op.create_index('ix_incident_embeddings_content_fingerprint','incident_embeddings',['content_fingerprint'])
def downgrade():
    op.drop_index('ix_incident_embeddings_content_fingerprint',table_name='incident_embeddings');op.drop_index('ix_incident_embeddings_organization_id',table_name='incident_embeddings');op.drop_index('ix_incident_embeddings_analysis_id',table_name='incident_embeddings');op.drop_table('incident_embeddings')