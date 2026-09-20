from alembic import op
import sqlalchemy as sa

revision = "0012_github_oauth"
down_revision = "0011_analysis_failed_command"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("github_user_id", sa.String(80), nullable=True))
        batch.add_column(sa.Column("github_login", sa.String(120), nullable=True))
    op.create_index("ix_users_github_user_id", "users", ["github_user_id"], unique=True)
    op.create_table(
        "oauth_login_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_hash", sa.String(128), nullable=False),
        sa.Column("code_verifier", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_oauth_login_states_state_hash", "oauth_login_states", ["state_hash"], unique=True)
    op.create_index("ix_oauth_login_states_expires_at", "oauth_login_states", ["expires_at"])

def downgrade():
    op.drop_index("ix_oauth_login_states_expires_at", table_name="oauth_login_states")
    op.drop_index("ix_oauth_login_states_state_hash", table_name="oauth_login_states")
    op.drop_table("oauth_login_states")
    op.drop_index("ix_users_github_user_id", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("github_login")
        batch.drop_column("github_user_id")