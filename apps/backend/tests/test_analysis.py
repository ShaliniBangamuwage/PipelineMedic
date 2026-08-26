from app.services.log_processing import process_log
from app.services.analyzer import analyze

def test_processing_removes_ansi_timestamps_duplicates_and_secrets():
    result=process_log("2025-01-01T00:00:00Z \x1b[31mERROR\x1b[0m token=ghp_abc123\nERROR token=ghp_abc123\n\n")
    assert "2025-01-01" not in result["cleaned_log"]
    assert result["cleaned_log"].count("ERROR") == 1
    assert "[REDACTED]" in result["cleaned_log"]

def test_classifier_detects_typescript():
    result=analyze("TS2322: Type string is not assignable", ["TS2322: Type string is not assignable"])
    assert result["category"] == "COMPILATION_ERROR"
    assert result["confidence"] > .9

def test_classifier_falls_back_to_unknown():
    assert analyze("nothing", [])["category"] == "UNKNOWN"

def test_build_step_and_missing_property_are_extracted():
    log="Run npm run build\nTS2741: Property 'email' is missing in type '{}' but required in type 'UserDto'."
    result=analyze(log, ["Run npm run build", "TS2741: Property 'email' is missing in type '{}' but required in type 'UserDto'."])
    assert result['failed_step'] == 'npm run build'
    assert "email" in result['root_cause'] and 'UserDto' in result['root_cause']

def test_evidence_lines_are_deduplicated():
    result=process_log("ERROR duplicate\nERROR duplicate\nERROR other")
    assert result['evidence'] == ['ERROR duplicate', 'ERROR other']
