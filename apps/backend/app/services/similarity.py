import re
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import FailureAnalysis

STOPWORDS={"error","failed","failure","the","and","step","workflow","process"}
def keywords(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text) if word.lower() not in STOPWORDS}

def find_similar(db: Session, item: FailureAnalysis, limit: int = 5, organization_id: str | None = None):
    terms=keywords(item.cleaned_log)
    query=select(FailureAnalysis).where(FailureAnalysis.id != item.id, FailureAnalysis.category == item.category)
    if organization_id: query=query.where(FailureAnalysis.organization_id == organization_id)
    candidates=db.scalars(query).all()
    scored=[]
    for candidate in candidates:
        other=keywords(candidate.cleaned_log)
        union=terms | other
        score=(len(terms & other) / len(union)) if union else 0
        if score > 0: scored.append((score,candidate))
    return [{"similarity":round(score,3),"analysis":candidate} for score,candidate in sorted(scored,key=lambda value:value[0],reverse=True)[:limit]]
