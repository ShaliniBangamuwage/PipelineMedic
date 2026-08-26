import re
from datetime import datetime, timezone
from app.core.config import settings
from app.models import FailureAnalysis, PRCommentDelivery, Repository
from app.services.github import GitHubClient, GitHubPermanentError, GitHubTemporaryError
from app.services.jobs import redact_error
from app.services.jobs import enqueue

MARKER = "<!-- pipelinemedic-analysis:{analysis_id} -->"
MAX_COMMENT_LENGTH = 6000
_MARKDOWN = re.compile(r"[`*_>#\[\]()]", re.MULTILINE)
_SECRET = re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key)\s*[=:]\s*[^\s,;]+")

def clean(value: object, limit: int = 300) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = _SECRET.sub(r"\1=[REDACTED]", text)
    return _MARKDOWN.sub("", text)[:limit]

def report(analysis: FailureAnalysis, include_similar: bool = False, similar: str | None = None, base_url: str = "") -> str:
    evidence = analysis.raw_log_excerpt.splitlines()[:5] if analysis.raw_log_excerpt else []
    lines = [MARKER.format(analysis_id=analysis.id), "## PipelineMedic", "",
             f"**Category:** {clean(analysis.category)}  ", f"**Severity:** {clean(analysis.severity)}  ", f"**Confidence:** {analysis.confidence:.0%}", "",
             f"**Root cause:** {clean(analysis.root_cause)}", f"**Failed step:** {clean(analysis.failed_step)}", "", "**Evidence:**"]
    lines.extend(f"- {clean(line, 240)}" for line in evidence)
    lines += ["", "**Suggested actions:** Developer review is required before applying a fix."]
    if include_similar and similar:
        lines += ["", f"**Similar resolved incident:** {clean(similar)}"]
    if base_url:
        lines += ["", f"[View analysis]({base_url.rstrip('/')}/analyses/{analysis.id})"]
    lines += ["", "_This AI/rule-based output requires developer review._"]
    return "\n".join(lines)[:MAX_COMMENT_LENGTH]

def delivery_out(item: PRCommentDelivery | None):
    if not item: return None
    return {"id": item.id, "status": item.status, "pullRequestNumber": item.pull_request_number,
            "githubCommentId": item.github_comment_id, "githubCommentUrl": item.github_comment_url,
            "attemptCount": item.attempt_count, "errorCode": item.last_error_code,
            "errorMessage": item.last_error_message, "createdAt": item.created_at.isoformat() if item.created_at else None,
            "deliveredAt": item.delivered_at.isoformat() if item.delivered_at else None}

def queue_delivery(db, analysis: FailureAnalysis, repository: Repository):
    existing = db.query(PRCommentDelivery).filter(PRCommentDelivery.repository_id == repository.id, PRCommentDelivery.analysis_id == analysis.id).first()
    if existing: return existing, False
    delivery = PRCommentDelivery(organization_id=analysis.organization_id, repository_id=repository.id, analysis_id=analysis.id, workflow_run_id=analysis.commit_sha, status="QUEUED")
    if not repository.pr_comments_enabled:
        delivery.status, delivery.last_error_code, delivery.last_error_message = "SKIPPED", "DISABLED", "PR comments are disabled"
    elif analysis.confidence < repository.pr_comment_min_confidence:
        delivery.status, delivery.last_error_code, delivery.last_error_message = "SKIPPED", "LOW_CONFIDENCE", "Analysis confidence is below the configured threshold"
    elif analysis.branch not in [branch.strip() for branch in repository.pr_comment_allowed_branches.split(",")]:
        delivery.status, delivery.last_error_code, delivery.last_error_message = "SKIPPED", "BRANCH_NOT_ALLOWED", "Analysis branch is not allowed"
    elif not settings.github_token:
        delivery.status, delivery.last_error_code, delivery.last_error_message = "SKIPPED", "MISSING_CREDENTIALS", "GitHub credentials are not configured"
    db.add(delivery); db.flush()
    if delivery.status == "QUEUED":
        enqueue(db, "PR_COMMENT_DELIVERY", analysis.organization_id, None, delivery.id)
    else:
        db.commit()
    return delivery, True

def deliver(db, delivery: PRCommentDelivery, analysis: FailureAnalysis, repository: Repository, client: GitHubClient):
    delivery.status = "SENDING"; delivery.attempt_count += 1; db.commit()
    try:
        candidates = client.pull_requests_for_run(repository.owner, repository.name, analysis.branch, analysis.commit_sha)
        pr = next((item for item in candidates if item.get("state") == "open"), None)
        if not pr:
            delivery.status = "SKIPPED"
            delivery.last_error_code = "CLOSED_PR" if candidates else "MISSING_PR"
            delivery.last_error_message = "No open pull request found"
            db.commit(); return
        delivery.pull_request_number = pr["number"]
        body = report(analysis, repository.pr_comment_include_similar_incident, base_url=settings.frontend_url)
        comments = client.comments(repository.owner, repository.name, pr["number"])
        existing = next((item for item in comments if MARKER.format(analysis_id=analysis.id) in item.get("body", "")), None)
        result = client.update_comment(repository.owner, repository.name, str(existing["id"]), body) if existing else client.create_comment(repository.owner, repository.name, pr["number"], body)
        delivery.github_comment_id = str(result.get("id")); delivery.github_comment_url = result.get("html_url"); delivery.status = "DELIVERED"; delivery.delivered_at = datetime.now(timezone.utc); delivery.last_error_code = None; delivery.last_error_message = None; db.commit()
    except GitHubTemporaryError as error:
        delivery.status = "RETRYING"; delivery.last_error_code = "TEMPORARY"; delivery.last_error_message = redact_error(error); db.commit(); raise
    except GitHubPermanentError as error:
        delivery.status = "FAILED"; delivery.last_error_code = "PERMISSION" if "403" in str(error) or "401" in str(error) else "GITHUB_ERROR"; delivery.last_error_message = redact_error(error); db.commit()