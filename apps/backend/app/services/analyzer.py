import re
from dataclasses import dataclass, field
from app.models import Category, Severity

RULES=[(Category.COMPILATION_ERROR, r"TS\d+|SyntaxError|compilation failed|cannot find symbol|type mismatch|target .* failed", .92), (Category.LINT_ERROR, r"lint|no-unused-vars|eslint|flake8|pylint|golangci-lint", .86), (Category.UNIT_TEST_FAILURE, r"test failed|assertion error|AssertionError|expected.*received|expected:|received:|FAIL\s+\S+|(?:^|\s)FAILED\s+\S+::|short test summary info|assert\s+.+(?:==|!=|<=|>=|<|>)\s*.+", .90), (Category.DEPENDENCY_ERROR, r"module not found|no module named|package not found|dependency resolution|npm ERR|pip.*resolution|could not find a version that satisfies", .88), (Category.CONFIGURATION_ERROR, r"(?i)(?:missing (?:required )?(?:environment variable|configuration|config(?:uration)? value|secret|config)|required (?:environment variable|configuration|config(?:uration)? value|secret) .*?(?:missing|not set|not defined|is required)|(?:environment variable|configuration|config(?:uration)? value|secret) .*?(?:required|missing)|missing required .*?(?:variable|value|config|configuration)|environment variable .*? is required|configuration .*?is required)", .86), (Category.DATABASE_MIGRATION_ERROR, r"migration failed|relation does not exist|SQL error|database.*refused", .88), (Category.CONTAINER_ERROR, r"Docker build failed|failed to build image|container exited", .90), (Category.AUTHORIZATION_ERROR, r"unauthorized|forbidden|permission denied|HTTP 40[13]", .91), (Category.NETWORK_TIMEOUT, r"timeout|DNS failure|connection reset|network unreachable", .87), (Category.DEPLOYMENT_ERROR, r"deploy(ment)? failed|release failed|rollout", .82)]


@dataclass
class FailureContext:
    category: str
    failed_step: str = "Unknown"
    error_type: str = "UNKNOWN"
    error_message: str = ""
    failing_file: str = ""
    failing_test: str = ""
    failing_command: str = ""
    assertion_evidence: str = ""
    stack_trace_excerpt: str = ""
    evidence_lines: list[str] = field(default_factory=list)


def _normalize_run_step(step: str) -> str:
    cleaned = step.strip()
    cleaned = re.sub(r"^(?:##\[(?:group|command)\])?Run\s+", "", cleaned, flags=re.I)
    cleaned = cleaned.strip()
    if not cleaned:
        return "Unknown"
    if re.match(r"(?i)^(?:python\s+-m\s+)?pytest(?:\s|$)", cleaned):
        return "pytest"
    return cleaned


def _extract_run_steps(lines: list[str]) -> list[tuple[int, str, str]]:
    steps = []
    for index, line in enumerate(lines):
        match = re.match(r"\s*(?:##\[(?:group|command)\])?Run\s+(.+?)\s*$", line, re.I)
        if match:
            raw_command = match.group(1).strip()
            steps.append((index, _normalize_run_step(raw_command), raw_command))
    return steps


def _find_failure_index(lines: list[str]) -> int | None:
    for idx, line in enumerate(lines):
        if re.search(r"AssertionError|FAILED\s+\S+::|short test summary info|TS\d+|npm ERR|ModuleNotFoundError|TypeError|ValueError|ImportError|SyntaxError|No such file or directory|##\[error\]|(?:^|\s)[A-Za-z0-9_./\\-]+\(\d+,\d+\):\s*error|(?:missing|required).*?(?:environment variable|configuration|config(?:uration)? value|secret|config)|(?:environment variable|configuration|config(?:uration)? value|secret).*?(?:required|missing)|error\s+(?:TS\d+|no-unused-vars|target .* failed|cannot find symbol|command not found|failed to|could not|module not found|permission denied|not found)", line, re.I):
            return idx
    return None


def _find_failed_run_step(cleaned_log: str) -> tuple[int, str, str] | None:
    lines = cleaned_log.splitlines()
    generic_exit = any(re.search(r"process completed with exit code \d+|job failed|workflow failed", line, re.I) for line in lines)
    has_real_failure_signal = any(re.search(r"AssertionError|FAILED\s+\S+::|short test summary info|TS\d+|npm ERR|ModuleNotFoundError|TypeError|ValueError|ImportError|SyntaxError|error:|failed to|No such file or directory|missing required .*?(?:environment variable|config(?:uration)?|secret)|required .*?(?:environment variable|config(?:uration)?|secret).*?(?:missing|not set|not defined)|environment variable .*? is required|configuration .*? is required|missing .*?(?:environment variable|config(?:uration)? value|required configuration)", line, re.I) for line in lines)
    if generic_exit and not has_real_failure_signal:
        return None

    run_steps = _extract_run_steps(lines)
    if not run_steps:
        return None

    failure_line_index = None
    for idx, line in enumerate(lines):
        if re.search(r"AssertionError|FAILED\s+\S+::|short test summary info|E\s+assert|missing required .*?(?:environment variable|config(?:uration)?|secret)|required .*?(?:environment variable|config(?:uration)?|secret).*?(?:missing|not set|not defined)|environment variable .*? is required|configuration .*? is required|TS\d+|npm ERR|ModuleNotFoundError|TypeError|ValueError|ImportError|SyntaxError|Process completed with exit code|##\[error\]", line, re.I):
            failure_line_index = idx
            break
    if failure_line_index is not None:
        for step_index, step_name, raw_command in reversed(run_steps):
            if step_index < failure_line_index:
                return step_index, step_name, raw_command

    return run_steps[-1]


def _extract_failed_step(cleaned_log: str, hits: list[str]) -> str:
    selected = _find_failed_run_step(cleaned_log)
    if selected:
        command = _extract_failing_command(cleaned_log)
        if command and command != selected[2] and (
            re.match(r"(?i)^(?:cd|mkdir|pwd|ls|echo)\s+", selected[1])
            or re.match(r"(?i)^(?:cd|mkdir|pwd|ls|echo)\s+", selected[2])
        ):
            return command
        return selected[1]
    return next((x for x in hits if "step" in x.lower()), "Unknown")


def _extract_error_type(cleaned_log: str) -> str:
    for pattern in [r"(AssertionError)", r"(TypeError)", r"(ValueError)", r"(ModuleNotFoundError)", r"(ImportError)", r"(PermissionError)", r"(ConnectionError)", r"(SyntaxError)", r"(RuntimeError)", r"(RuntimeException)"]:
        match = re.search(pattern, cleaned_log, re.I)
        if match:
            return match.group(1)
    if re.search(r"(?i)npm err|pip.*error|error:|failed", cleaned_log):
        return "ERROR"
    return "UNKNOWN"


def _extract_error_message(cleaned_log: str, evidence: list[str]) -> str:
    def score_line(line: str) -> int:
        candidate = line.strip()
        if re.search(r"AssertionError|TypeError|ValueError|ModuleNotFoundError|ImportError|PermissionError|ConnectionError|SyntaxError|FAILED\s+\S+::|TS\d+|npm ERR|E\s+\d+\s+\||error\s+(?:TS\d+|no-unused-vars|target .* failed|cannot find symbol|command not found|failed to|could not|not found)", candidate, re.I):
            return 100
        if re.search(r"(?:missing|required).*?(?:environment variable|configuration|config(?:uration)? value|secret|config)|(?:environment variable|config(?:uration)? value|secret).*?(?:required|missing)|missing required .*?(?:variable|value|config|configuration)", candidate, re.I):
            return 95
        if re.search(r"(FAILED\s+\S+|assert\s+.*(?:==|!=|<=|>=|<|>)\s*.+|error:|error\s+.*\b(?:missing|denied|not found|failed)\b)", candidate, re.I):
            return 80
        if re.search(r"FAILURES|short test summary info|traceback|Process completed with exit code", candidate, re.I):
            return 60
        return 0

    lines = cleaned_log.splitlines()
    failure_index = _find_failure_index(lines)
    run_steps = _extract_run_steps(lines)
    candidates = []

    if failure_index is not None:
        for step_index, _, _ in reversed(run_steps):
            if step_index < failure_index:
                next_step_index = next((candidate_step[0] for candidate_step in run_steps if candidate_step[0] > step_index), len(lines))
                window = [line.strip() for line in lines[step_index: min(next_step_index, failure_index + 1)] if line.strip()]
                for line in evidence:
                    candidate = line.strip()
                    if candidate and candidate in window:
                        candidates.append(candidate)
                if candidates:
                    break

    if not candidates:
        for line in evidence or lines:
            candidate = line.strip()
            if candidate and (score_line(candidate) > 0 or re.search(r"(?:error|failed|assert|traceback|TS\d+)", candidate, re.I)):
                candidates.append(candidate)

    if not candidates:
        for line in lines:
            if re.search(r"(assert|error|failed|exception|traceback)", line, re.I):
                candidates.append(line.strip())

    ranked = sorted(candidates, key=lambda item: score_line(item), reverse=True)
    return ranked[0] if ranked else cleaned_log.strip()[:250]


def _extract_file_and_test(cleaned_log: str) -> tuple[str, str]:
    failing_file = ""
    failing_test = ""
    match = re.search(r"(?im)^\s*FAILED\s+(?P<test>.+?::[A-Za-z0-9_]+)\b", cleaned_log)
    if match:
        failing_test = match.group('test').strip()
        failing_file = failing_test.rsplit('::', 1)[0]
    elif re.search(r"(?i)file\s+['\"]?([^'\"\s]+\.py|[^'\"\s]+\.ts|[^'\"\s]+\.js)[^'\"]*['\"]?", cleaned_log):
        path_match = re.search(r"(?i)(?:file|error in|at)\s+['\"]?([^'\"\s]+\.(?:py|ts|tsx|js|jsx|java|go|cs))[:\s]", cleaned_log)
        if path_match:
            failing_file = path_match.group(1)
    return failing_file, failing_test


def _extract_failing_command(cleaned_log: str) -> str:
    lines = cleaned_log.splitlines()
    selected = _find_failed_run_step(cleaned_log)
    if not selected:
        return ""
    selected_index = selected[0]
    run_steps = _extract_run_steps(lines)
    next_step_index = next((step[0] for step in run_steps if step[0] > selected_index), len(lines))
    block_lines = []
    run_match = ""
    command_pattern = r"(?i)(?:python\s+-m\s+)?pytest(?:\s|$)|npm\s+(?:test|run|ci|install)|npx\s+\S+|pnpm\s+test|go\s+test|mvn\s+test|dotnet\s+test|cargo\s+test|make\s+test|tsc\s+\S+"

    for line in lines[selected_index:next_step_index]:
        candidate = line.strip()
        if not candidate:
            continue

        run_match_obj = re.match(r"^\s*(?:##\[(?:group|command)\])?Run\s+(.+?)\s*$", candidate, re.I)
        if run_match_obj:
            run_candidate = run_match_obj.group(1).strip()
            if re.search(command_pattern, run_candidate):
                run_match = run_candidate
            continue

        if re.match(r"^##\[(?:group|command|endgroup)\]", candidate, re.I):
            continue
        if re.match(r"(?i)^(?:shell:|set\s+|export\s+|cd\s+|echo\s+)", candidate):
            continue
        if re.search(command_pattern, candidate):
            block_lines.append(candidate)

    if run_match:
        return run_match
    if block_lines:
        return block_lines[-1]
    return selected[2]


def _extract_assertion_evidence(cleaned_log: str) -> str:
    for line in cleaned_log.splitlines():
        if re.search(r"assert\s+.+(?:==|!=|<=|>=|<|>)\s*.+|AssertionError|expected.*received|E\s+assert", line, re.I):
            return line.strip()
    return ""


def _extract_stack_trace_excerpt(cleaned_log: str) -> str:
    lines = cleaned_log.splitlines()
    excerpt = []
    for line in lines:
        if any(token in line for token in ("Traceback", "File ", "AssertionError", "E   ", "FAILED")):
            excerpt.append(line.strip())
            if len(excerpt) >= 5:
                break
    return "\n".join(excerpt)


def _build_dynamic_recommendations(context: FailureContext) -> list[dict[str, object]]:
    actions = []
    if context.category == Category.UNIT_TEST_FAILURE.value:
        if context.failing_test:
            actions.append({"description": f"Inspect the failing assertion in {context.failing_test} and update the expected or actual value to match the observed behavior.", "priority": 1})
        if context.assertion_evidence:
            actions.append({"description": f"Review the assertion evidence: {context.assertion_evidence}", "priority": 2})
        actions.append({"description": f"Re-run {context.failing_command or 'the failing test command'} after the fix to confirm the regression is resolved.", "priority": 3})
    elif context.category == Category.DEPENDENCY_ERROR.value:
        actions.append({"description": f"Resolve the dependency issue behind: {context.error_message or 'missing package or module error'}.", "priority": 1})
        actions.append({"description": "Verify lockfiles, package versions, and installation steps before re-running CI.", "priority": 2})
    elif context.category == Category.COMPILATION_ERROR.value:
        actions.append({"description": f"Fix the compile error in {context.failing_file or 'the failing source file'} and re-run the build.", "priority": 1})
    elif context.category == Category.CONFIGURATION_ERROR.value:
        actions.append({"description": "Validate the missing or invalid configuration values in the failing environment and pipeline settings.", "priority": 1})
    else:
        actions.append({"description": f"Inspect the failing step '{context.failed_step}' and the evidence lines captured from the workflow output.", "priority": 1})
        actions.append({"description": "Verify the environment, command inputs, and pipeline state before the next run.", "priority": 2})
    return actions[:5]


def _failure_context_from_log(cleaned_log: str, evidence: list[str], category: str) -> FailureContext:
    failed_step = _extract_failed_step(cleaned_log, evidence)
    failing_file, failing_test = _extract_file_and_test(cleaned_log)
    error_type = _extract_error_type(cleaned_log)
    error_message = _extract_error_message(cleaned_log, evidence)
    assertion_evidence = _extract_assertion_evidence(cleaned_log)
    stack_trace_excerpt = _extract_stack_trace_excerpt(cleaned_log)
    return FailureContext(
        category=category,
        failed_step=failed_step,
        error_type=error_type,
        error_message=error_message,
        failing_file=failing_file,
        failing_test=failing_test,
        failing_command=_extract_failing_command(cleaned_log),
        assertion_evidence=assertion_evidence,
        stack_trace_excerpt=stack_trace_excerpt,
        evidence_lines=list(dict.fromkeys(line.strip() for line in evidence if line.strip()))[:12],
    )


def _normalize_fingerprint_value(value: str) -> str:
    if not value:
        return ""
    value = value.strip().lower()
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"[0-9a-f]{8,}", "", value)
    value = re.sub(r"(run_attempt|attempt|run_id|id|sha)[:=][^\s,;]+", "", value)
    value = re.sub(r"\d{4}-\d{2}-\d{2}[t\s]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:z)?", "", value)
    value = re.sub(r"\b\d+\b", "", value)
    value = re.sub(r"[^a-z0-9_./:-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def compute_failure_fingerprint(category: str, failed_step: str, error_type: str, error_message: str, failing_file: str, failing_test: str) -> str:
    parts = [
        _normalize_fingerprint_value(category),
        _normalize_fingerprint_value(failed_step),
        _normalize_fingerprint_value(error_type),
        _normalize_fingerprint_value(error_message),
        _normalize_fingerprint_value(failing_file),
        _normalize_fingerprint_value(failing_test),
    ]
    seed = "|".join(part for part in parts if part)
    import hashlib
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def analyze(cleaned_log: str, evidence: list[str]):
    scores=[]
    for category, pattern, confidence in RULES:
        hits=[line for line in evidence if re.search(pattern,line,re.I)]
        if hits: scores.append((len(hits)*confidence, category, confidence, hits))
    if not scores:
        context = _failure_context_from_log(cleaned_log, evidence, Category.UNKNOWN.value)
        return {"category":Category.UNKNOWN.value,"confidence":.25,"severity":Severity.LOW.value,"summary":"The workflow failed without a recognized signature.","root_cause":"Insufficient diagnostic evidence to identify a specific root cause.","failed_step":context.failed_step,"error_type":context.error_type,"error_message":context.error_message,"failing_file":context.failing_file,"failing_test":context.failing_test,"failing_command":context.failing_command,"assertion_evidence":context.assertion_evidence,"stack_trace_excerpt":context.stack_trace_excerpt,"evidence_lines":context.evidence_lines[:10],"evidence":context.evidence_lines[:10],"suggested_actions":[{"description":"Review the failed step and expand the log context.","priority":1}],"fingerprint":compute_failure_fingerprint(context.category, context.failed_step, context.error_type, context.error_message, context.failing_file, context.failing_test)}
    _, category, base, hits=max(scores,key=lambda item:item[0])
    severity=Severity.CRITICAL.value if category in (Category.DATABASE_MIGRATION_ERROR,Category.DEPLOYMENT_ERROR) else Severity.HIGH.value if base >= .9 else Severity.MEDIUM.value
    label=category.value.replace("_"," ").title()
    context = _failure_context_from_log(cleaned_log, evidence, category.value)
    failed_step=context.failed_step
    missing=re.search(r"TS2741.*Property ['\"]([^'\"]+)['\"].*required in type ['\"]([^'\"]+)", cleaned_log, re.I)
    root_cause = context.error_message or (context.evidence_lines[0] if context.evidence_lines else f"The log contains signatures associated with {label.lower()}.")
    if missing: root_cause=f"Property '{missing.group(1)}' is missing from the target {missing.group(2)} DTO or interface."
    recommendations = _build_dynamic_recommendations(context)
    if not recommendations:
        recommendations = [{"description": f"Inspect and remediate the {label.lower()} reported in the evidence.", "priority": 1}, {"description": "Re-run the workflow after applying the fix.", "priority": 2}]
    return {"category":category.value,"confidence":min(.99, base + min(.06,len(hits)*.01)),"severity":severity,"summary":f"{label} detected from workflow evidence.","root_cause":root_cause,"failed_step":failed_step,"error_type":context.error_type,"error_message":context.error_message,"failing_file":context.failing_file,"failing_test":context.failing_test,"failing_command":context.failing_command,"assertion_evidence":context.assertion_evidence,"stack_trace_excerpt":context.stack_trace_excerpt,"evidence_lines":context.evidence_lines[:10],"evidence":list(dict.fromkeys(hits))[:10],"suggested_actions":recommendations,"fingerprint":compute_failure_fingerprint(context.category,context.failed_step,context.error_type,context.error_message,context.failing_file,context.failing_test)}
