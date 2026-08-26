from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

def now(): return datetime.now(timezone.utc)

class Category(str, Enum):
    COMPILATION_ERROR="COMPILATION_ERROR"; UNIT_TEST_FAILURE="UNIT_TEST_FAILURE"; INTEGRATION_TEST_FAILURE="INTEGRATION_TEST_FAILURE"; DEPENDENCY_ERROR="DEPENDENCY_ERROR"; CONFIGURATION_ERROR="CONFIGURATION_ERROR"; DATABASE_MIGRATION_ERROR="DATABASE_MIGRATION_ERROR"; CONTAINER_ERROR="CONTAINER_ERROR"; DEPLOYMENT_ERROR="DEPLOYMENT_ERROR"; AUTHORIZATION_ERROR="AUTHORIZATION_ERROR"; NETWORK_TIMEOUT="NETWORK_TIMEOUT"; UNKNOWN="UNKNOWN"
class Severity(str, Enum): LOW="LOW"; MEDIUM="MEDIUM"; HIGH="HIGH"; CRITICAL="CRITICAL"
class OrganizationRole(str, Enum): OWNER="OWNER"; ADMIN="ADMIN"; DEVELOPER="DEVELOPER"; VIEWER="VIEWER"

class Repository(Base):
    __tablename__="repositories"
    __table_args__=(UniqueConstraint("owner", "name", name="uq_repository_owner_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str|None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    owner: Mapped[str] = mapped_column(String(100)); name: Mapped[str] = mapped_column(String(100)); default_branch: Mapped[str] = mapped_column(String(100), default="main"); active: Mapped[bool] = mapped_column(Boolean, default=True); pr_comments_enabled: Mapped[bool] = mapped_column(Boolean, default=False); pr_comment_min_confidence: Mapped[float] = mapped_column(Float, default=0.8); pr_comment_allowed_branches: Mapped[str] = mapped_column(Text, default="main"); pr_comment_include_similar_incident: Mapped[bool] = mapped_column(Boolean, default=True); pr_comment_include_patch: Mapped[bool] = mapped_column(Boolean, default=False); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    analyses: Mapped[list["FailureAnalysis"]] = relationship(back_populates="repository")

class FailureAnalysis(Base):
    __tablename__="analyses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str|None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    repository_id: Mapped[str|None] = mapped_column(ForeignKey("repositories.id"), nullable=True); workflow_name: Mapped[str] = mapped_column(String(200), default="Manual analysis"); branch: Mapped[str] = mapped_column(String(200), default="main"); commit_sha: Mapped[str] = mapped_column(String(100), default=""); source: Mapped[str] = mapped_column(String(20), default="DEMO"); category: Mapped[str] = mapped_column(String(50)); summary: Mapped[str] = mapped_column(String(500)); root_cause: Mapped[str] = mapped_column(Text); failed_step: Mapped[str] = mapped_column(String(200), default="Unknown"); confidence: Mapped[float] = mapped_column(Float); severity: Mapped[str] = mapped_column(String(20)); cleaned_log: Mapped[str] = mapped_column(Text); raw_log_excerpt: Mapped[str] = mapped_column(Text); resolved: Mapped[bool] = mapped_column(Boolean, default=False); actual_solution: Mapped[str|None] = mapped_column(Text, nullable=True); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    repository: Mapped[Repository|None] = relationship(back_populates="analyses")

class IncidentFeedback(Base):
    __tablename__="incident_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"))
    organization_id: Mapped[str|None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    accurate: Mapped[bool] = mapped_column(Boolean)
    actual_category: Mapped[str|None] = mapped_column(String(50), nullable=True)
    actual_solution: Mapped[str|None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class User(Base):
    __tablename__="users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Organization(Base):
    __tablename__="organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class OrganizationMember(Base):
    __tablename__="organization_members"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=OrganizationRole.VIEWER.value)
    __table_args__=(UniqueConstraint("organization_id", "user_id", name="uq_organization_member"),)

class RefreshToken(Base):
    __tablename__="refresh_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

class Invitation(Base):
    __tablename__="invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(20), default=OrganizationRole.DEVELOPER.value)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    invited_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class IncidentEmbedding(Base):
    __tablename__="incident_embeddings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), unique=True, index=True)
    organization_id: Mapped[str|None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    content_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    vector_json: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(80)); model: Mapped[str] = mapped_column(String(120)); dimensions: Mapped[int] = mapped_column(default=32)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Job(Base):
    __tablename__="jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str|None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(80)); status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    delivery_id: Mapped[str|None] = mapped_column(String(200), nullable=True, unique=True, index=True)
    workflow_run_id: Mapped[str|None] = mapped_column(String(80), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(default=0); error_message: Mapped[str|None] = mapped_column(Text, nullable=True); next_retry_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class PRCommentDelivery(Base):
    __tablename__ = "pr_comment_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str|None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)
    workflow_run_id: Mapped[str|None] = mapped_column(String(80), nullable=True)
    pull_request_number: Mapped[int|None] = mapped_column(nullable=True)
    github_comment_id: Mapped[str|None] = mapped_column(String(80), nullable=True)
    github_comment_url: Mapped[str|None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    last_error_code: Mapped[str|None] = mapped_column(String(40), nullable=True)
    last_error_message: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    delivered_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("repository_id", "analysis_id", name="uq_pr_comment_analysis"),)

class PatchSuggestion(Base):
    __tablename__ = "patch_suggestions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str|None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    repository_id: Mapped[str|None] = mapped_column(ForeignKey("repositories.id"), nullable=True, index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)
    provider: Mapped[str] = mapped_column(String(80)); model: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), index=True); unified_diff: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default=""); confidence: Mapped[float] = mapped_column(Float, default=0)
    risk_level: Mapped[str] = mapped_column(String(20), default="HIGH"); affected_files: Mapped[str] = mapped_column(Text, default="[]")
    validation_errors: Mapped[str] = mapped_column(Text, default="[]"); source_context_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    created_by_user_id: Mapped[str|None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class PatchDecision(Base):
    __tablename__ = "patch_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    patch_id: Mapped[str] = mapped_column(ForeignKey("patch_suggestions.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    decision: Mapped[str] = mapped_column(String(20)); feedback: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

Index("ix_analyses_category", FailureAnalysis.category)
Index("ix_analyses_repository_id", FailureAnalysis.repository_id)
Index("ix_analyses_branch", FailureAnalysis.branch)
Index("ix_analyses_resolved", FailureAnalysis.resolved)
Index("ix_analyses_created_at", FailureAnalysis.created_at)
