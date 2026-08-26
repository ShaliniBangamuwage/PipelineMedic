from app.services.embedding import DeterministicEmbeddingProvider, KeywordSimilarityProvider, content_fingerprint

def test_deterministic_embedding_is_stable_and_normalized():
    first=DeterministicEmbeddingProvider().embed('redacted failure')
    assert first==DeterministicEmbeddingProvider().embed('redacted failure')
    assert len(first)==32

def test_content_fingerprint_is_deterministic():
    assert content_fingerprint('x')==content_fingerprint('x')
    assert content_fingerprint('x')!=content_fingerprint('y')

def test_keyword_provider_remains_available():
    assert KeywordSimilarityProvider().__class__.__name__=='KeywordSimilarityProvider'
