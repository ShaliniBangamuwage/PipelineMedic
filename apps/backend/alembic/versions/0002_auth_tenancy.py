from alembic import op
import sqlalchemy as sa

revision="0002_auth_tenancy"
down_revision="0001_initial"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("users", sa.Column("id",sa.String(36),primary_key=True), sa.Column("email",sa.String(320),nullable=False), sa.Column("password_hash",sa.String(200),nullable=False), sa.Column("created_at",sa.DateTime(timezone=True)))
    op.create_index("ix_users_email","users",["email"],unique=True)
    op.create_table("organizations", sa.Column("id",sa.String(36),primary_key=True), sa.Column("name",sa.String(120),nullable=False), sa.Column("slug",sa.String(120),nullable=False), sa.Column("created_at",sa.DateTime(timezone=True)))
    op.create_index("ix_organizations_slug","organizations",["slug"],unique=True)
    op.create_table("organization_members", sa.Column("id",sa.String(36),primary_key=True), sa.Column("organization_id",sa.String(36),sa.ForeignKey("organizations.id"),nullable=False), sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id"),nullable=False), sa.Column("role",sa.String(20),nullable=False))
    op.create_index("uq_organization_member","organization_members",["organization_id","user_id"],unique=True)
    op.create_index("ix_organization_members_organization_id","organization_members",["organization_id"]); op.create_index("ix_organization_members_user_id","organization_members",["user_id"])
    op.create_table("refresh_tokens",sa.Column("id",sa.String(36),primary_key=True),sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id"),nullable=False),sa.Column("token_hash",sa.String(128),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("revoked_at",sa.DateTime(timezone=True)))
    op.create_index("ix_refresh_tokens_token_hash","refresh_tokens",["token_hash"],unique=True); op.create_index("ix_refresh_tokens_user_id","refresh_tokens",["user_id"]); op.create_index("ix_refresh_tokens_expires_at","refresh_tokens",["expires_at"])
    op.create_table("invitations",sa.Column("id",sa.String(36),primary_key=True),sa.Column("organization_id",sa.String(36),sa.ForeignKey("organizations.id"),nullable=False),sa.Column("email",sa.String(320),nullable=False),sa.Column("role",sa.String(20),nullable=False),sa.Column("token_hash",sa.String(128),nullable=False),sa.Column("invited_by_user_id",sa.String(36),sa.ForeignKey("users.id"),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("accepted_at",sa.DateTime(timezone=True)),sa.Column("revoked_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True)))
    op.create_index("ix_invitations_organization_id","invitations",["organization_id"]); op.create_index("ix_invitations_email","invitations",["email"]); op.create_index("ix_invitations_token_hash","invitations",["token_hash"],unique=True); op.create_index("ix_invitations_invited_by_user_id","invitations",["invited_by_user_id"]); op.create_index("ix_invitations_expires_at","invitations",["expires_at"])
    with op.batch_alter_table("repositories") as batch: batch.add_column(sa.Column("organization_id",sa.String(36),sa.ForeignKey("organizations.id",name="fk_repositories_organization"),nullable=True))
    op.create_index("ix_repositories_organization_id","repositories",["organization_id"])
    with op.batch_alter_table("analyses") as batch: batch.add_column(sa.Column("organization_id",sa.String(36),sa.ForeignKey("organizations.id",name="fk_analyses_organization"),nullable=True))
    op.create_index("ix_analyses_organization_id","analyses",["organization_id"])
    with op.batch_alter_table("incident_feedback") as batch: batch.add_column(sa.Column("organization_id",sa.String(36),sa.ForeignKey("organizations.id",name="fk_feedback_organization"),nullable=True))
    op.create_index("ix_incident_feedback_organization_id","incident_feedback",["organization_id"])

def downgrade():
    op.drop_index("ix_incident_feedback_organization_id",table_name="incident_feedback")
    with op.batch_alter_table("incident_feedback") as batch: batch.drop_column("organization_id")
    op.drop_index("ix_analyses_organization_id",table_name="analyses")
    with op.batch_alter_table("analyses") as batch: batch.drop_column("organization_id")
    op.drop_index("ix_repositories_organization_id",table_name="repositories")
    with op.batch_alter_table("repositories") as batch: batch.drop_column("organization_id")
    for index,table in [("ix_invitations_expires_at","invitations"),("ix_invitations_invited_by_user_id","invitations"),("ix_invitations_token_hash","invitations"),("ix_invitations_email","invitations"),("ix_invitations_organization_id","invitations")]: op.drop_index(index,table_name=table)
    op.drop_table("invitations")
    for index,table in [("ix_refresh_tokens_expires_at","refresh_tokens"),("ix_refresh_tokens_user_id","refresh_tokens"),("ix_refresh_tokens_token_hash","refresh_tokens")]: op.drop_index(index,table_name=table)
    op.drop_table("refresh_tokens"); op.drop_index("ix_organization_members_user_id",table_name="organization_members"); op.drop_index("ix_organization_members_organization_id",table_name="organization_members"); op.drop_index("uq_organization_member",table_name="organization_members"); op.drop_table("organization_members"); op.drop_index("ix_organizations_slug",table_name="organizations"); op.drop_table("organizations"); op.drop_index("ix_users_email",table_name="users"); op.drop_table("users")