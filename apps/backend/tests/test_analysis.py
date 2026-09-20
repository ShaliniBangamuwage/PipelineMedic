import pytest

from app.core.config import Settings
from app.services.log_processing import process_log
from app.services.analyzer import analyze
from app.services import ai as ai_service


class _FakeGroqResponse:
    def __init__(self, payload):
        self.choices = [type('Choice', (), {'message': type('Message', (), {'content': payload})()})()]

def test_processing_removes_ansi_timestamps_duplicates_and_secrets():
    result=process_log("2025-01-01T00:00:00Z \x1b[31mERROR\x1b[0m token=ghp_abc123\nERROR token=ghp_abc123\n\n")
    assert "2025-01-01" not in result["cleaned_log"]
    assert result["cleaned_log"].count("ERROR") == 1
    assert "[REDACTED]" in result["cleaned_log"]


def test_hybrid_ai_does_not_overwrite_strong_rule_result(monkeypatch):
    monkeypatch.setattr(ai_service.settings, 'ai_enabled', True)
    monkeypatch.setattr(ai_service.settings, 'groq_api_key', 'sk-test-key-123456')
    client = type('Client', (), {'chat': type('Chat', (), {'completions': type('Completions', (), {'create': lambda self, **kwargs: _FakeGroqResponse('{"summary":"bad","category":"CONFIGURATION_ERROR","rootCause":"environment variable not set","failedStep":"setup","evidence":["Process completed with exit code 1."],"suggestedActions":[{"description":"fake","priority":1}],"confidence":0.99,"severity":"HIGH"}')})()})()})()
    result = ai_service.analyze_with_fallback('Run pytest\nFAILED tests/test_example.py::test_fail - AssertionError', ['FAILED tests/test_example.py::test_fail - AssertionError'])
    assert result['category'] == 'UNIT_TEST_FAILURE'
    assert result['source'] == 'RULE'


def test_untrusted_ai_hallucination_is_rejected_when_rule_result_is_unknown(monkeypatch):
    monkeypatch.setattr(ai_service.settings, 'ai_enabled', True)
    monkeypatch.setattr(ai_service.settings, 'groq_api_key', 'sk-test-key-123456')
    client = type('Client', (), {'chat': type('Chat', (), {'completions': type('Completions', (), {'create': lambda self, **kwargs: _FakeGroqResponse('{"summary":"bad","category":"COMPILATION_ERROR","rootCause":"TypeScript error in app.ts","failedStep":"npm run build","evidence":["totally different log line"],"suggestedActions":[{"description":"fake","priority":1}],"confidence":0.99,"severity":"HIGH"}')})()})()})()
    monkeypatch.setattr(ai_service, 'GroqAnalyzer', lambda: type('Stub', (), {'analyze': lambda self, cleaned_log, evidence: ({'category': 'COMPILATION_ERROR', 'rootCause': 'TypeScript error in app.ts', 'failedStep': 'npm run build', 'evidence': ['totally different log line'], 'suggestedActions': [{'description': 'fake', 'priority': 1}], 'confidence': 0.99, 'severity': 'HIGH', 'summary': 'bad', 'source': 'AI'}, 'GROQ')})())
    result = ai_service.analyze_with_fallback('Run exit 1\nProcess completed with exit code 1.', ['Process completed with exit code 1.'])
    assert result['category'] == 'UNKNOWN'
    assert result['root_cause'] == 'Insufficient diagnostic evidence to identify a specific root cause.'


def test_ai_requests_are_redacted_before_provider_call(monkeypatch):
    calls = {}
    class FakeCompletions:
        def create(self, **kwargs):
            calls['prompt'] = kwargs['messages'][1]['content']
            return _FakeGroqResponse('{"summary":"okay","category":"UNKNOWN","rootCause":"not enough info","failedStep":"Unknown","evidence":[],"suggestedActions":[],"confidence":0.1,"severity":"LOW"}')
    class FakeClient:
        chat = type('Chat', (), {'completions': FakeCompletions()})()
    monkeypatch.setattr(ai_service.settings, 'ai_enabled', True)
    monkeypatch.setattr(ai_service.settings, 'groq_api_key', 'sk-test-key-123456')
    monkeypatch.setattr(ai_service, 'OpenAI', lambda *args, **kwargs: FakeClient())
    log = 'Authorization: Bearer ghp_secret123\nRun ./bootstrap.sh\nRuntimeError: bootstrap state is invalid\nProcess completed with exit code 1.'
    result = ai_service.analyze_with_fallback(log, ['RuntimeError: bootstrap state is invalid', 'Process completed with exit code 1.'])
    assert 'ghp_secret123' not in calls['prompt']
    assert 'pass@db' not in calls['prompt']
    assert result['source'] in {'RULE', 'AI', 'HYBRID'}


def test_ai_disabled_skips_provider_calls(monkeypatch):
    monkeypatch.setattr(ai_service.settings, 'ai_enabled', False)
    monkeypatch.setattr(ai_service.settings, 'groq_api_key', 'fake-key')
    assert ai_service.get_analyzer().__class__.__name__ == 'RuleBasedAnalyzer'


def test_ai_result_accepts_valid_json_groq_payload():
    payload = {"summary": "Build failed in pytest", "category": "UNIT_TEST_FAILURE", "rootCause": "Assertion mismatch in test suite", "failedStep": "pytest", "evidence": ["FAILED tests/test_example.py::test_fail - AssertionError"], "suggestedActions": [{"description": "Fix the assertion", "priority": 1}], "confidence": 0.91, "severity": "HIGH"}
    validated = ai_service.AIResult.model_validate(payload)
    assert validated.category == "UNIT_TEST_FAILURE"
    assert validated.confidence == 0.91


def test_ai_result_accepts_markdown_fenced_json_payload():
    content = '```json\n{"summary":"Build failed in pytest","category":"UNIT_TEST_FAILURE","rootCause":"Assertion mismatch in test suite","failedStep":"pytest","evidence":["FAILED tests/test_example.py::test_fail - AssertionError"],"suggestedActions":[{"description":"Fix the assertion","priority":1}],"confidence":0.91,"severity":"HIGH"}\n```'
    parsed = ai_service._extract_json_object(content)
    validated = ai_service.AIResult.model_validate(parsed)
    assert validated.failedStep == "pytest"


def test_ai_prompt_contract_restricts_categories_and_action_objects():
    contract = ai_service._ai_contract_prompt()
    assert 'COMPILATION_ERROR' in contract
    assert 'UNKNOWN' in contract
    assert 'suggestedActions' in contract
    assert 'description' in contract
    assert 'priority' in contract
    assert 'Deployment Validation' not in contract


def test_ai_result_rejects_missing_required_field():
    with pytest.raises(Exception):
        ai_service.AIResult.model_validate({"summary": "bad", "category": "UNIT_TEST_FAILURE", "evidence": ["line"], "confidence": 0.9, "severity": "HIGH"})


def test_ai_result_rejects_invalid_category():
    with pytest.raises(Exception):
        ai_service.AIResult.model_validate({"summary": "bad", "category": "NOT_A_REAL_CATEGORY", "rootCause": "bad", "evidence": ["line"], "confidence": 0.9, "severity": "HIGH"})


def test_ai_result_rejects_invalid_confidence():
    with pytest.raises(Exception):
        ai_service.AIResult.model_validate({"summary": "bad", "category": "UNIT_TEST_FAILURE", "rootCause": "bad", "evidence": ["line"], "confidence": 2.0, "severity": "HIGH"})


def test_ai_result_rejects_wrong_field_types():
    with pytest.raises(Exception):
        ai_service.AIResult.model_validate({"summary": "bad", "category": "UNIT_TEST_FAILURE", "rootCause": "bad", "evidence": "only a string", "confidence": 0.9, "severity": "HIGH"})


def test_ai_result_rejects_invented_category():
    with pytest.raises(Exception):
        ai_service.AIResult.model_validate({"summary": "bad", "category": "Deployment Validation", "rootCause": "bad", "failedStep": "deploy", "evidence": ["Deployment target 'staging-eu' rejected the release"], "suggestedActions": [{"description": "Fix it", "priority": 1}], "confidence": 0.9, "severity": "HIGH"})


def test_ai_result_accepts_unknown_category_and_valid_action_objects():
    validated = ai_service.AIResult.model_validate({"summary": "insufficient evidence", "category": "UNKNOWN", "rootCause": "Insufficient diagnostic evidence to identify a specific root cause.", "failedStep": "Unknown", "evidence": ["Process completed with exit code 1."], "suggestedActions": [{"description": "Check the failing command", "priority": 1}], "confidence": 0.3, "severity": "LOW"})
    assert validated.category == "UNKNOWN"
    assert validated.suggestedActions[0].description == "Check the failing command"


def test_ai_result_rejects_string_suggested_actions():
    with pytest.raises(Exception):
        ai_service.AIResult.model_validate({"summary": "bad", "category": "UNKNOWN", "rootCause": "bad", "failedStep": "Unknown", "evidence": ["line"], "suggestedActions": ["Fix it"], "confidence": 0.3, "severity": "LOW"})


def test_unsupported_ai_claims_are_rejected_by_grounding_checks(monkeypatch):
    unsupported = {"summary": "Bad", "category": "UNIT_TEST_FAILURE", "rootCause": "This is unrelated to the supplied run", "failedStep": "unknown", "evidence": ["totally different log line"], "suggestedActions": [{"description": "Fix it", "priority": 1}], "confidence": 0.99, "severity": "HIGH"}
    log = "Run echo \"setup\"\nProcess completed with exit code 1."
    assert ai_service._is_supported_ai_result(unsupported, log, ["Process completed with exit code 1."], {"category": "UNKNOWN"}) is False


def test_supported_evidence_grounded_ai_is_accepted(monkeypatch):
    supported = {"summary": "Build failed in pytest", "category": "UNIT_TEST_FAILURE", "rootCause": "Assertion mismatch in test suite", "failedStep": "pytest", "evidence": ["FAILED tests/test_example.py::test_fail - AssertionError"], "suggestedActions": [{"description": "Fix the assertion", "priority": 1}], "confidence": 0.91, "severity": "HIGH"}
    log = "Run pytest\nFAILED tests/test_example.py::test_fail - AssertionError"
    assert ai_service._is_supported_ai_result(supported, log, ["FAILED tests/test_example.py::test_fail - AssertionError"], {"category": "UNKNOWN"}) is True


def test_provider_http_failure_falls_back_to_deterministic(monkeypatch):
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise TimeoutError("Groq request timed out")
    monkeypatch.setattr(ai_service.settings, 'ai_enabled', True)
    monkeypatch.setattr(ai_service.settings, 'groq_api_key', 'sk-test-key-123456')
    monkeypatch.setattr(ai_service.settings, 'groq_model', 'openai/gpt-oss-120b')
    monkeypatch.setattr(ai_service, 'get_analyzer', lambda: ai_service.GroqAnalyzer(FakeClient()))
    result = ai_service.analyze_with_fallback('Run pytest\nFAILED tests/test_example.py::test_fail - AssertionError', ['FAILED tests/test_example.py::test_fail - AssertionError'])
    assert result['category'] == 'UNIT_TEST_FAILURE'
    assert result['source'] == 'RULE'


def test_malformed_json_falls_back_to_deterministic(monkeypatch):
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    class Choice:
                        message = type('Message', (), {'content': '{bad json'})
                    return type('Response', (), {'choices': [Choice()]})()
    monkeypatch.setattr(ai_service.settings, 'ai_enabled', True)
    monkeypatch.setattr(ai_service.settings, 'groq_api_key', 'sk-test-key-123456')
    monkeypatch.setattr(ai_service.settings, 'groq_model', 'openai/gpt-oss-120b')
    monkeypatch.setattr(ai_service, 'get_analyzer', lambda: ai_service.GroqAnalyzer(FakeClient()))
    result = ai_service.analyze_with_fallback('Run pytest\nFAILED tests/test_example.py::test_fail - AssertionError', ['FAILED tests/test_example.py::test_fail - AssertionError'])
    assert result['category'] == 'UNIT_TEST_FAILURE'
    assert result['source'] == 'RULE'


def test_generic_deployment_failure_keeps_context_and_allows_ai_fallback(monkeypatch):
    log = '''##[group]Run echo "Starting deployment validation..."
echo "Starting deployment validation..."
echo "Deployment target 'staging-eu' rejected the release because service manifest revision 'v42' is incompatible with the currently deployed gateway contract 'v41'."
echo "The release requires gateway contract v42 before this application revision can be deployed."
exit 1
##[endgroup]
Starting deployment validation...
Deployment target 'staging-eu' rejected the release because service manifest revision 'v42' is incompatible with the currently deployed gateway contract 'v41'.
The release requires gateway contract v42 before this application revision can be deployed.
##[error]Process completed with exit code 1.
'''
    processed = process_log(log)
    evidence_text = '\n'.join(processed['evidence'])
    assert 'Deployment target' in evidence_text
    assert 'gateway contract' in evidence_text
    rule_result = analyze(processed['ai_log'], processed['evidence'])
    assert rule_result['category'] == 'UNKNOWN'

    monkeypatch.setattr(ai_service.settings, 'ai_enabled', True)
    monkeypatch.setattr(ai_service.settings, 'groq_api_key', 'sk-test-key-123456')
    monkeypatch.setattr(ai_service.settings, 'groq_model', 'openai/gpt-oss-120b')
    monkeypatch.setattr(ai_service, 'GroqAnalyzer', lambda: type('Stub', (), {'analyze': lambda self, cleaned_log, evidence: ({'category': 'DEPLOYMENT_ERROR', 'summary': 'Deployment contract mismatch', 'rootCause': 'The release requires gateway contract v42 before this application revision can be deployed.', 'failedStep': 'echo "Starting deployment validation..."', 'evidence': ['Deployment target \'staging-eu\' rejected the release because service manifest revision \'v42\' is incompatible with the currently deployed gateway contract \'v41\'.', 'The release requires gateway contract v42 before this application revision can be deployed.'], 'suggestedActions': [{'description': 'Verify gateway contract compatibility before deployment.', 'priority': 1}], 'confidence': 0.82, 'severity': 'HIGH'}, 'GROQ')})())
    result = ai_service.analyze_with_fallback(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'DEPLOYMENT_ERROR'
    assert result['source'] in {'AI', 'HYBRID'}


def test_ai_enabled_with_valid_key_uses_groq(monkeypatch):
    monkeypatch.setattr(ai_service.settings, 'ai_enabled', True)
    monkeypatch.setattr(ai_service.settings, 'groq_api_key', 'sk-test-key-123456')
    monkeypatch.setattr(ai_service.settings, 'groq_model', 'openai/gpt-oss-120b')
    assert isinstance(ai_service.get_analyzer(), ai_service.GroqAnalyzer)


def test_missing_groq_key_falls_back_to_rule_analyzer(monkeypatch):
    monkeypatch.setattr(ai_service.settings, 'ai_enabled', True)
    monkeypatch.setattr(ai_service.settings, 'groq_api_key', '')
    monkeypatch.setattr(ai_service.settings, 'groq_model', 'openai/gpt-oss-120b')
    assert isinstance(ai_service.get_analyzer(), ai_service.RuleBasedAnalyzer)


def test_settings_load_environment_variables_case_insensitively(monkeypatch):
    monkeypatch.setenv('AI_ENABLED', 'true')
    monkeypatch.setenv('GROQ_API_KEY', 'sk-test-key-123456')
    monkeypatch.setenv('GROQ_MODEL', 'openai/gpt-oss-120b')
    monkeypatch.setenv('AI_TIMEOUT_SECONDS', '25')
    monkeypatch.setenv('AI_MAX_LOG_CHARS', '45000')
    settings = Settings()
    assert settings.ai_enabled is True
    assert settings.groq_api_key == 'sk-test-key-123456'
    assert settings.groq_model == 'openai/gpt-oss-120b'
    assert settings.ai_timeout_seconds == 25
    assert settings.ai_max_log_chars == 45000


def test_worker_and_backend_share_the_same_settings_object():
    import app.worker as worker_module
    assert ai_service.settings is worker_module.settings


def test_classifier_detects_typescript():
    result=analyze("TS2322: Type string is not assignable", ["TS2322: Type string is not assignable"])
    assert result["category"] == "COMPILATION_ERROR"
    assert result["confidence"] > .9

def test_processing_keeps_bare_typescript_diagnostics_as_evidence():
    result=process_log("TS2322: Type string is not assignable")
    assert result["evidence"] == ["TS2322: Type string is not assignable"]

def test_classifier_falls_back_to_unknown():
    assert analyze("nothing", [])["category"] == "UNKNOWN"

def test_unknown_exit_code_does_not_invent_root_cause_or_step():
    result = analyze(
        'Run echo "PipelineMedic CI failure test"\n##[error]Process completed with exit code 1.',
        ['##[error]Process completed with exit code 1.'],
    )
    assert result['category'] == 'UNKNOWN'
    assert result['root_cause'] == 'Insufficient diagnostic evidence to identify a specific root cause.'
    assert result['failed_step'] == 'Unknown'

def test_classifier_detects_real_pytest_failure_and_step():
    log = """##[group]Run pytest
============================= test session starts =============================
collected 1 item
test_pipeline.py F
=================================== FAILURES ===================================
________________________ test_pipeline_medic_failure _________________________
    assert 1 == 2
E   assert 1 == 2
E   AssertionError
=========================== short test summary info ============================
FAILED tests/test_pipeline.py::test_pipeline_medic_failure - assert 1 == 2
============================== 1 failed in 0.12s ==============================="""
    processed = process_log(log)
    result = analyze(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'UNIT_TEST_FAILURE'
    assert result['failed_step'] == 'pytest'
    assert result['root_cause']


def test_classifier_uses_failing_pytest_step_after_successful_checkout_steps():
    log = """##[group]Run actions/checkout@v4
/usr/bin/git version
Successfully checked out repository
##[endgroup]

##[group]Set up Python 3.12
Python 3.12.4
##[endgroup]

##[group]Run python -m pip install pytest
Collecting pytest
Successfully installed pytest
##[endgroup]

##[group]Run pytest
pytest -q tests/test_pipeline_medic.py
============================= test session starts =============================
collected 1 item
test_pipeline_medic.py F
=================================== FAILURES ===================================
________________________ test_pipeline_medic_failure _________________________
    assert 1 == 2
E   assert 1 == 2
E   AssertionError
=========================== short test summary info ============================
FAILED tests/test_pipeline_medic.py::test_pipeline_medic_failure - assert 1 == 2
##[error]Process completed with exit code 1.
"""
    processed = process_log(log)
    result = analyze(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'UNIT_TEST_FAILURE'
    assert result['failed_step'] == 'pytest'
    assert 'AssertionError' in result['evidence'][0] or any('AssertionError' in item for item in result['evidence'])

def test_classifier_uses_failing_step_and_command_after_successful_setup_steps():
    log = """\ufeff2026-09-19T13:02:15.7303030Z ##[group]Run actions/checkout@v4
Successfully checked out repository
##[endgroup]
\ufeff2026-09-19T13:02:15.7304000Z ##[group]Run actions/setup-python@v5
Successfully set up CPython (3.12.14)
##[endgroup]
\ufeff2026-09-19T13:02:15.7305000Z ##[group]Run pip install pytest
Successfully installed pytest
##[endgroup]
\ufeff2026-09-19T13:02:15.7306000Z ##[group]Run mkdir -p tests
created test file
##[endgroup]
\ufeff2026-09-19T13:02:15.7307000Z ##[group]Run pytest -q tests/test_pipeline_medic.py
FAILURES
test_pipeline_medic_failure
assert 1 == 2
tests/test_pipeline_medic.py:2: AssertionError
FAILED tests/test_pipeline_medic.py::test_pipeline_medic_failure - assert 1 == 2
Process completed with exit code 1.
"""
    processed = process_log(log)
    result = analyze(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'UNIT_TEST_FAILURE'
    assert result['failed_step'] == 'pytest'
    assert any('Re-run pytest -q tests/test_pipeline_medic.py' in action['description'] for action in result['suggested_actions'])
def test_build_step_and_missing_property_are_extracted():
    log="Run npm run build\nTS2741: Property 'email' is missing in type '{}' but required in type 'UserDto'."
    result=analyze(log, ["Run npm run build", "TS2741: Property 'email' is missing in type '{}' but required in type 'UserDto'."])
    assert result['failed_step'] == 'npm run build'
    assert "email" in result['root_cause'] and 'UserDto' in result['root_cause']

def test_evidence_lines_are_deduplicated():
    result=process_log("ERROR duplicate\nERROR duplicate\nERROR other")
    assert result['evidence'] == ['ERROR duplicate', 'ERROR other']


def test_missing_environment_variable_is_classified_as_configuration_error():
    log = '''##[group]Run if [ -z "${REQUIRED_ENV_KEY:-}" ]; then
if [ -z "${REQUIRED_ENV_KEY:-}" ]; then
echo "Missing required environment variable: REQUIRED_ENV_KEY"
exit 1
fi
shell: /usr/bin/bash -e {0}
##[endgroup]
Missing required environment variable: REQUIRED_ENV_KEY
##[error]Process completed with exit code 1.
'''
    processed = process_log(log)
    result = analyze(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'CONFIGURATION_ERROR'
    assert 'Missing required environment variable:' in result['root_cause']
    assert 'Process completed with exit code 1.' not in result['root_cause']
    assert result['failed_step'] == 'if [ -z "${REQUIRED_ENV_KEY:-}" ]; then' or result['failed_step'] == 'if [ -z "${REQUIRED_ENV_KEY:-}" ]; then\nif [ -z "${REQUIRED_ENV_KEY:-}" ]; then'


def test_missing_environment_variable_after_checkout_selects_the_real_run_block():
    log = '''##[group]Checking out the ref
/usr/bin/git checkout --progress --force
##[endgroup]

##[group]Run if [ -z "${PIPELINEMEDIC_REQUIRED_ENDPOINT:-}" ]; then
if [ -z "${PIPELINEMEDIC_REQUIRED_ENDPOINT:-}" ]; then
echo "Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT"
exit 1
fi
shell: /usr/bin/bash -e {0}
##[endgroup]
Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT
##[error]Process completed with exit code 1.
'''
    processed = process_log(log)
    result = analyze(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'CONFIGURATION_ERROR'
    assert 'Missing required environment variable: PIPELINEMEDIC_REQUIRED_ENDPOINT' in result['root_cause']
    assert 'Checking out the ref' not in (result['failed_step'] or '')
    assert 'PIPELINEMEDIC_REQUIRED_ENDPOINT' in (result['failing_command'] or '') or 'if [ -z "${PIPELINEMEDIC_REQUIRED_ENDPOINT:-}" ]' in (result['failed_step'] or '')


def test_generic_exit_one_block_remains_unknown_even_when_structurally_identified():
    log = '''##[group]Run exit 1
exit 1
shell: /usr/bin/bash -e {0}
##[endgroup]
##[error]Process completed with exit code 1.
'''
    processed = process_log(log)
    result = analyze(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'UNKNOWN'
    assert result['confidence'] < 0.5
    assert result['root_cause'] == 'Insufficient diagnostic evidence to identify a specific root cause.'


def test_missing_required_configuration_value_is_classified_as_configuration_error():
    log = '''##[group]Run python app.py
Missing required configuration value: DATABASE_URL
exit 1
shell: /usr/bin/bash -e {0}
##[endgroup]
##[error]Process completed with exit code 1.
'''
    processed = process_log(log)
    result = analyze(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'CONFIGURATION_ERROR'
    assert 'Missing required configuration value:' in result['root_cause']
    assert 'DATABASE_URL' in result['root_cause']


def test_generic_exit_one_without_diagnostic_evidence_remains_unknown():
    result = analyze('Run exit 1\nProcess completed with exit code 1.', ['Process completed with exit code 1.'])
    assert result['category'] == 'UNKNOWN'
    assert result['root_cause'] == 'Insufficient diagnostic evidence to identify a specific root cause.'


def test_harmless_environment_and_config_mentions_do_not_trigger_configuration_failure():
    result = analyze(
        'Run echo "Environment summary: preview mode enabled"\nRun echo "configuration check passed"\nProcess completed with exit code 0.',
        ['Environment summary: preview mode enabled', 'configuration check passed', 'Process completed with exit code 0.'],
    )
    assert result['category'] == 'UNKNOWN'


def test_missing_value_does_not_expose_secret_contents_from_redaction_path():
    log = 'Authorization: Bearer ghp_exampletoken123\nMissing required configuration value: API_TOKEN\nexit 1'
    processed = process_log(log)
    result = analyze(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'CONFIGURATION_ERROR'
    assert 'ghp_' not in result['root_cause']
    assert 'API_TOKEN' in result['root_cause']
    assert '[REDACTED]' in processed['cleaned_log']


def test_compilation_error_prefers_actual_compile_diagnostic_over_successful_setup_output():
    log = '''##[group]Run npm install
npm install
added 1 package
"test": "echo \"Error: no test specified\" && exit 1"
##[endgroup]

##[group]Run cd compiler-test
cd compiler-test
npx tsc app.ts --noEmit
shell: bash
##[endgroup]

##[error]app.ts(1,7): error TS2322: Type 'string' is not assignable to type 'number'.
##[error]Process completed with exit code 1.
'''
    processed = process_log(log)
    result = analyze(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'COMPILATION_ERROR'
    assert 'TS2322' in result['root_cause']
    assert 'npx tsc app.ts --noEmit' in (result['failing_command'] or '')
    assert 'package.json' not in result['root_cause'].lower()


def test_later_failure_evidence_beats_earlier_misleading_success_output():
    log = '''##[group]Run echo "Everything succeeded"
echo "Error: no issues"
echo "FAILED"
##[endgroup]

##[group]Run python -m pytest tests/test_order.py
pytest tests/test_order.py
============================= test session starts =============================
collected 1 item

test_order.py F
=================================== FAILURES ===================================
________________________ test_order_works _________________________
    assert 1 == 2
E   assert 1 == 2
E   AssertionError
=========================== short test summary info ============================
FAILED tests/test_order.py::test_order_works - assert 1 == 2
##[error]Process completed with exit code 1.
'''
    processed = process_log(log)
    result = analyze(processed['ai_log'], processed['evidence'])
    assert result['category'] == 'UNIT_TEST_FAILURE'
    assert 'AssertionError' in result['root_cause'] or 'assert 1 == 2' in result['root_cause']
    assert result['failing_command'] == 'python -m pytest tests/test_order.py'
