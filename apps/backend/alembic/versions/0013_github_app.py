from alembic import op
import sqlalchemy as sa

revision = "0013_github_app"
down_revision = "0012_github_oauth"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "github_installations" not in tables:
        op.create_table(
            "github_installations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("github_installation_id", sa.String(80), nullable=False),
            sa.Column("github_account_id", sa.String(80), nullable=False),
            sa.Column("github_account_login", sa.String(120), nullable=False),
            sa.Column("github_account_type", sa.String(40), nullable=False),
            sa.Column("repository_selection", sa.String(20), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True)),
            sa.Column("updated_at", sa.DateTime(timezone=True)),
        )
    if "github_installation_states" not in tables:
        op.create_table(
            "github_installation_states",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("state_hash", sa.String(128), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True)),
        )
    repository_columns = {column["name"] for column in inspector.get_columns("repositories")}
    if "credential_source" not in repository_columns:
        op.add_column("repositories", sa.Column("credential_source", sa.String(20), nullable=False, server_default="PAT"))
    if "github_repository_id" not in repository_columns:
        op.add_column("repositories", sa.Column("github_repository_id", sa.String(80), nullable=True))
    if "github_installation_id" not in repository_columns:
        op.add_column("repositories", sa.Column("github_installation_id", sa.String(36), sa.ForeignKey("github_installations.id"), nullable=True))
    indexes = {index["name"] for table in ("github_installations", "github_installation_states", "repositories") for index in inspector.get_indexes(table)}
    for name, table, columns, unique in (
        ("ix_github_installations_organization_id", "github_installations", ["organization_id"], False),
        ("ix_github_installations_github_installation_id", "github_installations", ["github_installation_id"], True),
        ("ix_github_installation_states_state_hash", "github_installation_states", ["state_hash"], True),
        ("ix_github_installation_states_user_id", "github_installation_states", ["user_id"], False),
        ("ix_github_installation_states_organization_id", "github_installation_states", ["organization_id"], False),
        ("ix_repositories_github_repository_id", "repositories", ["github_repository_id"], False),
        ("ix_repositories_github_installation_id", "repositories", ["github_installation_id"], False),
    ):
        if name not in indexes:
            op.create_index(name, table, columns, unique=unique)


def downgrade():
    op.drop_index("ix_repositories_github_installation_id", table_name="repositories")
    op.drop_index("ix_repositories_github_repository_id", table_name="repositories")
    op.drop_column("repositories", "github_installation_id")
    op.drop_column("repositories", "github_repository_id")
    op.drop_column("repositories", "credential_source")
    op.drop_index("ix_github_installation_states_organization_id", table_name="github_installation_states")
    op.drop_index("ix_github_installation_states_user_id", table_name="github_installation_states")
    op.drop_index("ix_github_installation_states_state_hash", table_name="github_installation_states")
    op.drop_table("github_installation_states")
    op.drop_index("ix_github_installations_github_installation_id", table_name="github_installations")
    op.drop_index("ix_github_installations_organization_id", table_name="github_installations")
    op.drop_table("github_installations")
