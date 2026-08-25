from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

def now(): return datetime.now(timezone.utc)

class Category(str, Enum):
    COMPILATION_ERROR="COMPILATION_ERROR"; UNIT_TEST_FAILURE="UNIT_TEST_FAILURE"; INTEGRATION_TEST_FAILURE="INTEGRATION_TEST_FAILURE"; DEPENDENCY_ERROR="DEPENDENCY_ERROR"; CONFIGURATION_ERROR="CONFIGURATION_ERROR"; DATABASE_MIGRATION_ERROR="DATABASE_MIGRATION_ERROR"; CONTAINER_ERROR="CONTAINER_ERROR"; DEPLOYMENT_ERROR="DEPLOYMENT_ERROR"; AUTHORIZATION_ERROR="AUTHORIZATION_ERROR"; NETWORK_TIMEOUT="NETWORK_TIMEOUT"; UNKNOWN="UNKNOWN"
class Severity(str, Enum): LOW="LOW"; MEDIUM="MEDIUM"; HIGH="HIGH"; CRITICAL="CRITICAL"

class Repository(Base):
    __tablename__="repositories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner: Mapped[str] = mapped_column(String(100)); name: Mapped[str] = mapped_column(String(100)); default_branch: Mapped[str] = mapped_column(String(100), default="main"); active: Mapped[bool] = mapped_column(Boolean, default=True); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    analyses: Mapped[list["FailureAnalysis"]] = relationship(back_populates="repository")

class FailureAnalysis(Base):
    __tablename__="analyses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    repository_id: Mapped[str|None] = mapped_column(ForeignKey("repositories.id"), nullable=True); workflow_name: Mapped[str] = mapped_column(String(200), default="Manual analysis"); branch: Mapped[str] = mapped_column(String(200), default="main"); commit_sha: Mapped[str] = mapped_column(String(100), default=""); source: Mapped[str] = mapped_column(String(20), default="DEMO"); category: Mapped[str] = mapped_column(String(50)); summary: Mapped[str] = mapped_column(String(500)); root_cause: Mapped[str] = mapped_column(Text); failed_step: Mapped[str] = mapped_column(String(200), default="Unknown"); confidence: Mapped[float] = mapped_column(Float); severity: Mapped[str] = mapped_column(String(20)); cleaned_log: Mapped[str] = mapped_column(Text); raw_log_excerpt: Mapped[str] = mapped_column(Text); resolved: Mapped[bool] = mapped_column(Boolean, default=False); actual_solution: Mapped[str|None] = mapped_column(Text, nullable=True); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    repository: Mapped[Repository|None] = relationship(back_populates="analyses")
