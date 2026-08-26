from pydantic import BaseModel, Field

class RepositoryCreate(BaseModel):
    owner: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    default_branch: str = Field(default="main", min_length=1, max_length=100)
    active: bool = True

class RepositoryUpdate(BaseModel):
    default_branch: str | None = Field(default=None, min_length=1, max_length=100)
    active: bool | None = None
    pr_comments_enabled: bool | None = None
    pr_comment_min_confidence: float | None = Field(default=None, ge=0, le=1)
    pr_comment_allowed_branches: str | None = Field(default=None, min_length=1, max_length=1000)
    pr_comment_include_similar_incident: bool | None = None
    pr_comment_include_patch: bool | None = None

class PRCommentSettings(BaseModel):
    pr_comments_enabled: bool
    pr_comment_min_confidence: float = Field(ge=0, le=1)
    pr_comment_allowed_branches: str = Field(min_length=1, max_length=1000)
    pr_comment_include_similar_incident: bool = True
    pr_comment_include_patch: bool = False

class FeedbackCreate(BaseModel):
    accurate: bool
    actual_category: str | None = None
    actual_solution: str | None = None

class ResolveCreate(BaseModel):
    actual_solution: str | None = None

class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)

class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)

class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = "DEVELOPER"

class MemberUpdate(BaseModel):
    role: str
