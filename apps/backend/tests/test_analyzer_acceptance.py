import pytest

from app.services.analyzer import analyze
from app.services.log_processing import process_log


def result(log: str) -> dict:
    processed = process_log(log)
    return analyze(processed["ai_log"], processed["evidence"])


@pytest.mark.parametrize(
    ("name", "log", "category"),
    [
        ("pytest assertion", "Run python -m pytest tests/test_orders.py\nE assert total == expected\nAssertionError", "UNIT_TEST_FAILURE"),
        ("pytest import", "Run pytest tests/test_imports.py\nModuleNotFoundError: No module named 'billing_core'", "DEPENDENCY_ERROR"),
        ("jest failure", "Run npm test\nFAIL src/cart.test.ts\nExpected: 3\nReceived: 2", "UNIT_TEST_FAILURE"),
        ("npm dependency", "Run npm ci\nnpm ERR! code ERESOLVE\nnpm ERR! dependency resolution failed", "DEPENDENCY_ERROR"),
        ("pip dependency", "Run python -m pip install -r requirements.txt\npip error: Could not find a version that satisfies the requirement", "DEPENDENCY_ERROR"),
        ("typescript build", "Run npm run build\nTS2345: Argument of type string is not assignable", "COMPILATION_ERROR"),
        ("lint", "Run npm run lint\nerror: no-unused-vars at src/app.ts:4", "LINT_ERROR"),
        ("docker build", "Run docker build .\nDocker build failed: failed to solve", "CONTAINER_ERROR"),
        ("configuration", "Run deploy\nmissing environment variable DATABASE_URL", "CONFIGURATION_ERROR"),
        ("permission", "Run deploy\nError: permission denied while accessing the cluster", "AUTHORIZATION_ERROR"),
        ("command missing", "Run ./scripts/release.sh\n/bin/sh: ./scripts/release.sh: No such file or directory", "UNKNOWN"),
        ("generic exit", "Run ./scripts/check.sh\nProcess completed with exit code 1.", "UNKNOWN"),
    ],
)
def test_failure_families_are_evidence_driven(name, log, category):
    output = result(log)
    assert output["category"] == category, name
    assert output["root_cause"]
    assert output["confidence"] <= 0.99
    if category == "UNKNOWN":
        if name == "generic exit":
            assert output["failed_step"] == "Unknown"
            assert output["root_cause"] == "Insufficient diagnostic evidence to identify a specific root cause."


def test_step_command_and_evidence_follow_the_actual_failing_step():
    output = result(
        "Run actions/checkout@v4\ncheckout complete\n"
        "Run python -m pip install requests\ninstalled\n"
        "Run python scripts/verify_orders.py\nValueError: invalid order state\nProcess completed with exit code 1."
    )
    assert output["failed_step"] == "python scripts/verify_orders.py"
    assert output["failing_command"] == "python scripts/verify_orders.py"
    assert any("invalid order state" in line for line in output["evidence"])


@pytest.mark.parametrize(
    "log",
    [
        "\ufeff2026-09-20T00:00:00Z \x1b[31mRun npm run build\x1b[0m\nTS7006: parameter implicitly has an any type",
        "Run python -m pytest\nTraceback (most recent call last):\n  File \"tests/test_api.py\", line 8\nAssertionError: expected response",
        "Run make verify\nwarning\nwarning\nerror: target verify failed\nerror: target verify failed",
    ],
)
def test_noisy_timestamp_ansi_bom_and_multiline_logs_remain_analyzable(log):
    output = result(log)
    assert output["category"] != "UNKNOWN"
    assert output["evidence"]


def test_successful_workflow_is_not_classified_as_a_failure():
    output = result("Run npm test\nAll tests passed\nProcess completed with exit code 0.")
    assert output["category"] == "UNKNOWN"
    assert output["root_cause"] == "Insufficient diagnostic evidence to identify a specific root cause."