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
