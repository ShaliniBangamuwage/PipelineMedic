from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def initialize_database(db_engine=None):
    active_engine = db_engine or engine
    try:
        Base.metadata.create_all(active_engine)
    except (IntegrityError, ProgrammingError) as exc:
        message = str(exc).lower()
        if "duplicate" not in message and "already exists" not in message and "pg_type_typname_nsp_index" not in message:
            raise
    ensure_legacy_sqlite_schema(active_engine)


def _legacy_analysis_columns_sql(is_sqlite: bool) -> dict[str, str]:
    if is_sqlite:
        return {
            "workflow_run_id": "VARCHAR(80)",
            "failed_command": "VARCHAR(500)",
            "suggested_actions": "TEXT DEFAULT '[]'",
            "fingerprint": "VARCHAR(128) DEFAULT ''",
            "occurrence_count": "INTEGER DEFAULT 1",
            "first_seen": "DATETIME",
            "last_seen": "DATETIME",
            "resolved": "BOOLEAN DEFAULT 0",
            "status": "VARCHAR(20) DEFAULT 'OPEN'",
            "resolved_at": "DATETIME",
            "resolved_by": "VARCHAR(36)",
            "resolution_note": "TEXT",
            "analysis_time_minutes": "FLOAT DEFAULT 0",
            "resolution_time_minutes": "FLOAT DEFAULT 0",
            "actual_solution": "TEXT",
        }
    return {
        "workflow_run_id": "VARCHAR(80)",
        "failed_command": "VARCHAR(500)",
        "suggested_actions": "TEXT DEFAULT '[]'",
        "fingerprint": "VARCHAR(128) DEFAULT ''",
        "occurrence_count": "INTEGER DEFAULT 1",
        "first_seen": "TIMESTAMP WITH TIME ZONE",
        "last_seen": "TIMESTAMP WITH TIME ZONE",
        "resolved": "BOOLEAN DEFAULT FALSE",
        "status": "VARCHAR(20) DEFAULT 'OPEN'",
        "resolved_at": "TIMESTAMP WITH TIME ZONE",
        "resolved_by": "VARCHAR(36)",
        "resolution_note": "TEXT",
        "analysis_time_minutes": "FLOAT DEFAULT 0",
        "resolution_time_minutes": "FLOAT DEFAULT 0",
        "actual_solution": "TEXT",
    }


def ensure_legacy_sqlite_schema(db_engine=None):
    active_engine = db_engine or engine
    is_sqlite = str(active_engine.url).startswith("sqlite") if hasattr(active_engine, "url") else settings.database_url.startswith("sqlite")
    with active_engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        for table in ("repositories", "analyses", "incident_feedback"):
            if table in tables:
                columns = {column["name"] for column in inspect(connection).get_columns(table)}
                if "organization_id" not in columns:
                    if is_sqlite:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN organization_id VARCHAR(36)"))
                    else:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS organization_id VARCHAR(36)"))
        if "repositories" in tables:
            columns = {column["name"] for column in inspect(connection).get_columns("repositories")}
            for column_name, column_sql in {
                "default_branch": "VARCHAR(100) DEFAULT 'main'",
                "active": "BOOLEAN DEFAULT 1",
                "pr_comments_enabled": "BOOLEAN DEFAULT 0",
                "pr_comment_min_confidence": "FLOAT DEFAULT 0.8",
                "pr_comment_allowed_branches": "TEXT DEFAULT 'main'",
                "pr_comment_include_similar_incident": "BOOLEAN DEFAULT 1",
                "pr_comment_include_patch": "BOOLEAN DEFAULT 0",
                "github_token": "TEXT",
                "credential_source": "VARCHAR(20) NOT NULL DEFAULT 'PAT'",
                "github_repository_id": "VARCHAR(80)",
                "github_installation_id": "VARCHAR(36)",
                "webhook_secret": "VARCHAR(255) NOT NULL DEFAULT ''",
            }.items():
                if column_name not in columns:
                    if is_sqlite:
                        connection.execute(text(f"ALTER TABLE repositories ADD COLUMN {column_name} {column_sql}"))
                    else:
                        connection.execute(text(f"ALTER TABLE repositories ADD COLUMN IF NOT EXISTS {column_name} {column_sql}"))

            if is_sqlite:
                table_sql = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='repositories'")).scalar() or ""
                normalized = table_sql.lower().replace('"', '').replace(' ', '')
                has_legacy_global_unique = (
                    'unique(owner,name)' in normalized
                    or 'unique(name,owner)' in normalized
                    or 'constraintuq_repository_owner_nameunique(owner,name)' in normalized
                )
                if has_legacy_global_unique:
                    table_info = connection.execute(text("PRAGMA table_info(repositories)")).fetchall()
                    cols = []
                    fk_clause = ""
                    for row in table_info:
                        cid, name, ctype, notnull, default_value, pk = row
                        col_sql = f'"{name}" {ctype or "TEXT"}'
                        if notnull:
                            col_sql += " NOT NULL"
                        if default_value not in (None, "") and default_value != "NULL":
                            col_sql += f" DEFAULT {default_value}"
                        if pk:
                            col_sql += " PRIMARY KEY"
                        cols.append(col_sql)
                        if name == "organization_id":
                            fk_clause = ", FOREIGN KEY (organization_id) REFERENCES organizations (id)"
                    create_sql = "CREATE TABLE repositories_rebuilt (" + ", ".join(cols) + fk_clause + ")"
                    connection.execute(text(create_sql))
                    old_column_names = [row[1] for row in table_info]
                    insert_cols = ", ".join(f'"{col_name}"' for col_name in old_column_names)
                    connection.execute(text(f"INSERT INTO repositories_rebuilt ({insert_cols}) SELECT {insert_cols} FROM repositories"))
                    connection.execute(text("DROP TABLE repositories"))
                    connection.execute(text("ALTER TABLE repositories_rebuilt RENAME TO repositories"))
                index_rows = connection.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='repositories'")).fetchall()
                legacy_index_names = {row[0] for row in index_rows if row[0] in {"uq_repository_owner_name", "uq_repository_org_owner_name"}}
                if not legacy_index_names:
                    legacy_sql = connection.execute(text("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='repositories' AND sql IS NOT NULL")).fetchall()
                    legacy_index_names = {row[0] for row in legacy_sql if row[0] and ("UNIQUE" in row[0].upper() and "owner" in row[0].lower() and "name" in row[0].lower())}
                    legacy_index_names = {name for name in legacy_index_names if name}
                for index_name in sorted(legacy_index_names):
                    if index_name:
                        connection.execute(text(f"DROP INDEX IF EXISTS \"{index_name}\""))
                existing_org_unique = connection.execute(text("SELECT 1 FROM sqlite_master WHERE type='index' AND tbl_name='repositories' AND name='uq_repository_org_owner_name'")).fetchone()
                if not existing_org_unique:
                    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_repository_org_owner_name ON repositories (organization_id, owner, name)"))

        for table in ("workflow_runs", "jobs", "analyses"):
            if table in tables:
                columns = {column["name"] for column in inspect(connection).get_columns(table)}
                if table == "analyses":
                    for column_name, column_sql in _legacy_analysis_columns_sql(is_sqlite).items():
                        if column_name not in columns:
                            if is_sqlite:
                                connection.execute(text(f"ALTER TABLE analyses ADD COLUMN {column_name} {column_sql}"))
                            else:
                                connection.execute(text(f"ALTER TABLE analyses ADD COLUMN IF NOT EXISTS {column_name} {column_sql}"))
                if "run_attempt" not in columns:
                    if is_sqlite:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN run_attempt INTEGER"))
                    else:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS run_attempt INTEGER"))
        if "workflow_runs" in tables and not is_sqlite:
            connection.execute(text("ALTER TABLE workflow_runs DROP CONSTRAINT IF EXISTS uq_workflow_run_github_id"))
            connection.execute(text("ALTER TABLE workflow_runs DROP CONSTRAINT IF EXISTS uq_workflow_run_github_attempt"))
            connection.execute(text("ALTER TABLE workflow_runs ADD CONSTRAINT uq_workflow_run_github_attempt UNIQUE (repository_id, github_run_id, run_attempt)"))

        if "analyses" in tables and "repositories" in tables:
            connection.execute(text(
                "UPDATE analyses SET organization_id = "
                "(SELECT organization_id FROM repositories WHERE repositories.id = analyses.repository_id) "
                "WHERE analyses.organization_id IS NULL AND analyses.repository_id IS NOT NULL"
            ))

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
