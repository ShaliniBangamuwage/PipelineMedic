from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import hashlib, hmac, logging
from app.core.config import settings
from app.db import Base, engine, get_db
from app.models import FailureAnalysis, Repository
from app.services.log_processing import process_log
from app.services.analyzer import analyze

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app=FastAPI(title="PipelineMedic API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], allow_methods=["*"], allow_headers=["*"])
Base.metadata.create_all(engine)

def out(item):
    return {"id":item.id,"summary":item.summary,"rootCause":item.root_cause,"category":item.category,"severity":item.severity,"confidence":item.confidence,"source":item.source,"workflowName":item.workflow_name,"branch":item.branch,"commitSha":item.commit_sha,"failedStep":item.failed_step,"cleanedLog":item.cleaned_log,"evidence":item.raw_log_excerpt.splitlines() if item.raw_log_excerpt else [],"resolved":item.resolved,"actualSolution":item.actual_solution,"createdAt":item.created_at.isoformat() if item.created_at else None,"repository":f"{item.repository.owner}/{item.repository.name}" if item.repository else None}

@app.get("/api/health")
def health(): return {"status":"healthy","service":"PipelineMedic API","version":"1.0.0"}

@app.post("/api/demo/analyze")
async def demo_analyze(log: str=Form(""), repository: str=Form(""), workflow: str=Form("Manual analysis"), branch: str=Form("main"), commit_sha: str=Form(""), file: UploadFile|None=File(None), db: Session=Depends(get_db)):
    if file:
        if file.filename and not file.filename.lower().endswith((".log",".txt")): raise HTTPException(400,"Only .log and .txt files are supported")
        content=await file.read()
        if len(content)>settings.max_log_size_bytes: raise HTTPException(413,"Log exceeds the configured size limit")
        log=content.decode("utf-8",errors="replace")
    try: processed=process_log(log,settings.max_log_size_bytes,settings.max_ai_log_characters)
    except ValueError as exc: raise HTTPException(400,str(exc))
    result=analyze(processed["cleaned_log"],processed["evidence"])
    repo=None
    if repository and "/" in repository:
        owner,name=repository.split("/",1); repo=db.scalar(select(Repository).where(Repository.owner==owner,Repository.name==name))
        if not repo: repo=Repository(owner=owner,name=name); db.add(repo); db.flush()
    item=FailureAnalysis(repository_id=repo.id if repo else None,workflow_name=workflow,branch=branch,commit_sha=commit_sha,source="DEMO",category=result["category"],summary=result["summary"],root_cause=result["root_cause"],failed_step=result["failed_step"],confidence=result["confidence"],severity=result["severity"],cleaned_log=processed["cleaned_log"],raw_log_excerpt="\n".join(result["evidence"]))
    db.add(item); db.commit(); db.refresh(item); return {**out(item),"suggestedActions":result["suggested_actions"],"demoMode":not settings.ai_enabled}

@app.get("/api/analyses")
def analyses(page:int=1,pageSize:int=20,db:Session=Depends(get_db)):
    total=db.scalar(select(func.count()).select_from(FailureAnalysis)) or 0; rows=db.scalars(select(FailureAnalysis).order_by(FailureAnalysis.created_at.desc()).offset((page-1)*pageSize).limit(pageSize)).all(); return {"items":[out(x) for x in rows],"page":page,"pageSize":pageSize,"total":total}

@app.get("/api/analyses/{analysis_id}")
def detail(analysis_id:str,db:Session=Depends(get_db)):
    item=db.get(FailureAnalysis,analysis_id)
    if not item: raise HTTPException(404,"Analysis not found")
    return out(item)

@app.patch("/api/analyses/{analysis_id}/resolve")
def resolve(analysis_id:str,db:Session=Depends(get_db)):
    item=db.get(FailureAnalysis,analysis_id)
    if not item: raise HTTPException(404,"Analysis not found")
    item.resolved=True; db.commit(); db.refresh(item); return out(item)

@app.get("/api/dashboard/summary")
def summary(db:Session=Depends(get_db)):
    total=db.scalar(select(func.count()).select_from(FailureAnalysis)) or 0; resolved=db.scalar(select(func.count()).where(FailureAnalysis.resolved)) or 0; avg=db.scalar(select(func.avg(FailureAnalysis.confidence))) or 0; common=db.execute(select(FailureAnalysis.category,func.count()).group_by(FailureAnalysis.category).order_by(func.count().desc())).first(); repos=db.scalar(select(func.count()).select_from(Repository)) or 0
    return {"totalFailures":total,"resolvedFailures":resolved,"unresolvedFailures":total-resolved,"resolutionRate":round(resolved/total*100,1) if total else 0,"averageConfidence":round(avg*100,1),"mostCommonCategory":common[0] if common else "NONE","repositoriesMonitored":repos}

@app.post("/api/webhooks/github")
async def webhook(request:Request, background_tasks:BackgroundTasks, db:Session=Depends(get_db)):
    body=await request.body(); signature=request.headers.get("x-hub-signature-256","")
    if settings.github_webhook_secret and not hmac.compare_digest("sha256="+hmac.new(settings.github_webhook_secret.encode(),body,hashlib.sha256).hexdigest(),signature): raise HTTPException(401,"Invalid webhook signature")
    event=request.headers.get("x-github-event",""); payload=await request.json()
    if event=="ping": return {"ok":True,"event":"ping"}
    if event!="workflow_run": return {"ok":True,"ignored":True}
    run=payload.get("workflow_run",{})
    if run.get("conclusion")!="failure": return {"ok":True,"ignored":True}
    if db.scalar(select(FailureAnalysis).where(FailureAnalysis.commit_sha==run.get("head_sha",""),FailureAnalysis.workflow_name==run.get("name",""))): return {"ok":True,"duplicate":True}
    background_tasks.add_task(lambda: None)
    return {"ok":True,"queued":True}
