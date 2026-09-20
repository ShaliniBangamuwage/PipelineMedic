import re

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SECRET = re.compile(r"(?i)(bearer\s+|gh[pousr]_[A-Za-z0-9_]+|(?:token|password|secret|api[_-]?key)\s*[=:]\s*)[^\s,;]+")
TIMESTAMP = re.compile(r"^\s*(?:\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?Z?|\[?\d\d:\d\d:\d\d(?:\.\d+)?\]?)[ ]*")
DIAGNOSTIC_PATTERNS = (
    r"error|failed|failure|exception|fatal|denied|timeout|not found|assertion|traceback|npm err|migration|TS\d+|TypeScript|\bFAIL\b|expected:|received:|missing (?:required )?(?:environment|configuration|config(?:uration)?|secret)|required (?:environment|configuration|config(?:uration)?) .*?(?:missing|not set|not defined)|environment variable .*? is required|configuration .*? is required|missing .*?(?:environment variable|config(?:uration)? value)|no-unused-vars|rejected|incompatible|requires .* before .* can|gateway contract|manifest revision|deployment target|release requires|not compatible|contract mismatch|unable to|could not"
)


def _is_diagnostic_line(candidate: str) -> bool:
    return bool(candidate) and re.search(DIAGNOSTIC_PATTERNS, candidate, re.I)


def process_log(text: str, max_bytes: int = 5_000_000, max_chars: int = 30_000):
    if not isinstance(text, str) or not text.strip(): raise ValueError("A non-empty log is required")
    if len(text.encode("utf-8")) > max_bytes: raise ValueError("Log exceeds the configured size limit")
    lines=[]
    for line in ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = line.lstrip("\ufeff")
        line = TIMESTAMP.sub("", line)
        line = SECRET.sub(lambda m: m.group(1) + "[REDACTED]", line)
        lines.append(line.rstrip())
    collapsed=[]
    for line in lines:
        if collapsed and collapsed[-1] == line: continue
        if line or (collapsed and collapsed[-1]): collapsed.append(line)
    cleaned="\n".join(collapsed).strip()
    important=[]
    seen=set()
    for line in collapsed:
        candidate=line.strip()
        if not candidate or candidate in seen:
            continue
        if _is_diagnostic_line(candidate):
            important.append(candidate)
            seen.add(candidate)
            continue
        if re.match(r"^(?:Deployment target|The release requires|service manifest|gateway contract|manifest revision|Unable to|Could not)", candidate, re.I):
            important.append(candidate)
            seen.add(candidate)
    return {"cleaned_log": cleaned, "evidence": important[:30], "ai_log": cleaned[:max_chars]}
