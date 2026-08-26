from io import BytesIO
from zipfile import ZipFile
from unittest.mock import Mock
import app.services.ai as ai
from app.services.ai import GroqAnalyzer, analyze_with_fallback
from app.services.github import GitHubClient
from app.services.similarity import keywords

def test_groq_result_is_validated_and_evidence_is_restricted():
    client=Mock(); client.chat.completions.create.return_value=Mock(choices=[Mock(message=Mock(content='{"summary":"x","category":"COMPILATION_ERROR","rootCause":"bad type","failedStep":"build","evidence":["TS2322","invented"],"suggestedActions":[{"description":"fix","priority":1}],"confidence":0.9,"severity":"HIGH"}'))])
    result,provider=GroqAnalyzer(client).analyze('TS2322', ['TS2322'])
    assert provider=='GROQ' and result['evidence']==['TS2322']

def test_ai_failure_falls_back_without_network(monkeypatch):
    client=Mock(); client.chat.completions.create.side_effect=TimeoutError()
    analyzer=GroqAnalyzer(client)
    monkeypatch.setattr(ai, 'get_analyzer', lambda: analyzer)
    result,provider=analyze_with_fallback('npm ERR module not found',['npm ERR module not found'])
    assert provider=='RULE_BASED'

def test_zip_logs_are_extracted_safely():
    buffer=BytesIO()
    with ZipFile(buffer,'w') as archive:
        archive.writestr('job.txt','ERROR module not found')
        archive.writestr('../unsafe.txt','should not be read')
    response=Mock(status_code=200,content=buffer.getvalue(),headers={})
    client=Mock(); client.get.return_value=response
    text=GitHubClient('demo-token',client).workflow_logs('owner','repo',123)
    assert 'module not found' in text and 'should not be read' not in text

def test_similarity_keywords_are_normalized():
    assert keywords('ERROR: Module Not Found') == {'module','not','found'}
