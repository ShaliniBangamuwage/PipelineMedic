import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from app.core.config import settings

@dataclass
class PatchValidation:
    valid: bool
    affected_files: list[str]
    added_lines: int
    removed_lines: int
    total_changed_lines: int
    forbidden_paths: list[str]
    validation_errors: list[str]
    risk_level: str

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
_PATH = re.compile(r"^(?:---|\+\+\+) (?:a/|b/)?(.+)$", re.MULTILINE)
_SECRET_LINE = re.compile(r"(?i)(ghp_[a-z0-9]{8,}|github_pat_[a-z0-9_]{8,}|-----begin (?:rsa|openssh|ec) private key-----|(?:token|secret|password|api[_-]?key)\s*[=:])")

def validate_unified_diff(diff: str, dependency_incident: bool = False) -> PatchValidation:
    errors: list[str] = []; forbidden: list[str] = []; files: list[str] = []
    if not diff or "diff --git " not in diff or "--- " not in diff or "+++ " not in diff: errors.append("Not a unified diff")
    if "GIT binary patch" in diff or "Binary files" in diff: errors.append("Binary patches are not allowed")
    for match in _PATH.finditer(diff):
        path = match.group(1).strip()
        if path == "/dev/null": continue
        normalized = PurePosixPath(path)
        lockfile = normalized.name in {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
        if normalized.is_absolute() or ".." in normalized.parts or path.startswith((".env", ".git/")) or lockfile and not dependency_incident or normalized.name in {"id_rsa", "id_ed25519"} or any(part in {"vendor", "node_modules", "dist", "build", "generated"} for part in normalized.parts) or normalized.suffix in {".min.js", ".min.css"}:
            forbidden.append(path)
        if path not in files: files.append(path)
    if forbidden: errors.append("Forbidden file path")
    if len(files) > settings.patch_max_files: errors.append("Too many files")
    allowed = tuple(x.strip() for x in settings.patch_allowed_extensions.split(",") if x.strip())
    if any(not file.endswith(allowed) for file in files): errors.append("File extension is not allowed")
    lines = diff.splitlines(); added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++")); removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    if any(_SECRET_LINE.search(line) for line in lines if line.startswith("+") and not line.startswith("+++")): errors.append("Added lines contain a secret")
    if not any(_HUNK.match(line) for line in lines): errors.append("Missing hunk header")
    if added + removed > settings.patch_max_changed_lines: errors.append("Too many changed lines")
    if len(diff.encode()) > settings.patch_max_bytes: errors.append("Patch is too large")
    risk = "CRITICAL" if removed > 100 else "HIGH" if errors else "LOW"
    return PatchValidation(not errors, files, added, removed, added + removed, forbidden, errors, risk)