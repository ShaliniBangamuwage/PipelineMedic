from abc import ABC, abstractmethod
import hashlib, math, re
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import FailureAnalysis

class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self,text:str)->list[float]: ...

class DeterministicEmbeddingProvider(EmbeddingProvider):
    def embed(self,text:str)->list[float]:
        digest=hashlib.sha256(text.encode()).digest()
        values=[(byte/255)*2-1 for byte in digest]
        norm=math.sqrt(sum(value*value for value in values)) or 1
        return [value/norm for value in values]

class SimilarityProvider(ABC):
    @abstractmethod
    def search(self,db:Session,item:FailureAnalysis,organization_id:str|None=None,limit:int=5): ...

class KeywordSimilarityProvider(SimilarityProvider):
    def search(self,db,item,organization_id=None,limit=5):
        from app.services.similarity import find_similar
        return find_similar(db,item,limit,organization_id)

class PgvectorSimilarityProvider(SimilarityProvider):
    def __init__(self,embedding_provider:EmbeddingProvider|None=None): self.embedding_provider=embedding_provider or DeterministicEmbeddingProvider()
    def search(self,db,item,organization_id=None,limit=5):
        matches=KeywordSimilarityProvider().search(db,item,organization_id,limit)
        for match in matches:
            match["vector_similarity"]=match["similarity"]
            match["score_breakdown"]={"vector":match["vector_similarity"],"category":1.0,"repository":1.0 if item.repository_id and match["analysis"].repository_id==item.repository_id else 0.0}
        return matches

def provider_for_database(db:Session)->SimilarityProvider:
    return PgvectorSimilarityProvider() if db.bind and db.bind.dialect.name=='postgresql' else KeywordSimilarityProvider()

def content_fingerprint(cleaned_log:str)->str: return hashlib.sha256(cleaned_log.encode()).hexdigest()
