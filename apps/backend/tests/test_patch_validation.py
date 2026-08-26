from app.services.patch_validation import validate_unified_diff

def valid():
    return 'diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n'

def test_valid_unified_diff():
    result = validate_unified_diff(valid())
    assert result.valid and result.affected_files == ['app.py'] and result.total_changed_lines == 2

def test_rejects_prose_traversal_binary_and_env():
    assert not validate_unified_diff('just a suggestion').valid
    assert 'Forbidden file path' in validate_unified_diff(valid().replace('app.py', '../.env')).validation_errors
    assert not validate_unified_diff(valid() + 'Binary files a/x b/x differ\n').valid

def test_limits_files_lines_and_extensions(monkeypatch):
    monkeypatch.setattr('app.services.patch_validation.settings.patch_max_files', 0)
    result = validate_unified_diff(valid())
    assert 'Too many files' in result.validation_errors
