from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def ensure_legacy_sqlite_schema():
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        for table in ("repositories", "analyses", "incident_feedback"):
            if table in inspect(connection).get_table_names():
                columns={column["name"] for column in inspect(connection).get_columns(table)}
                if "organization_id" not in columns:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN organization_id VARCHAR(36)"))

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
