from unittest.mock import Mock
import pytest
from app.services.patch_generation import PatchProvider, PatchProviderError, PatchResponse, generate_and_validate
from app.services.patch_validation import validate_unified_diff

class Provider(PatchProvider):
    def __init__(self, value): self.value = value
    def generate(self, source_context, failure): return self.value

def test_valid_provider_response_is_validated():
    diff = 'diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n'
    result, validation = generate_and_validate(Provider(PatchResponse(unified_diff=diff, explanation='fix', confidence=.8)), 'source', 'failure')
    assert validation.valid and result.confidence == .8

def test_prose_only_response_is_rejected():
    result = validate_unified_diff('Use this fix instead.')
    assert not result.valid and result.validation_errors

def test_provider_failures_are_explicit():
    class Broken(PatchProvider):
        def generate(self, source_context, failure): raise PatchProviderError('provider unavailable')
    with pytest.raises(PatchProviderError): Broken().generate('x', 'y')
