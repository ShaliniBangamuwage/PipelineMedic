import re

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SECRET = re.compile(r"(?i)(bearer\s+|gh[pousr]_[A-Za-z0-9_]+|(?:token|password|secret|api[_-]?key)\s*[=:]\s*)[^\s,;]+")
TIMESTAMP = re.compile(r"^\s*(?:\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?Z?|\[?\d\d:\d\d:\d\d(?:\.\d+)?\]?)[ ]*")

def process_log(text: str, max_bytes: int = 5_000_000, max_chars: int = 30_000):
    if not isinstance(text, str) or not text.strip(): raise ValueError("A non-empty log is required")
    if len(text.encode("utf-8")) > max_bytes: raise ValueError("Log exceeds the configured size limit")
    lines=[]
    for line in ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n").splitlines():
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
        if candidate and re.search(r"(?i)(error|failed|failure|exception|fatal|denied|timeout|not found|assertion|traceback|npm err|migration|TS\d+|TypeScript)", candidate) and candidate not in seen:
            important.append(candidate)
            seen.add(candidate)
    return {"cleaned_log": cleaned, "evidence": important[:30], "ai_log": cleaned[:max_chars]}
