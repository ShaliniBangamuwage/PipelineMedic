import re
from app.models import Category, Severity

RULES=[(Category.COMPILATION_ERROR, r"TS\d+|SyntaxError|compilation failed|cannot find symbol|type mismatch", .92), (Category.UNIT_TEST_FAILURE, r"test failed|assertion error|expected.*received|pytest|jest", .90), (Category.DEPENDENCY_ERROR, r"module not found|package not found|dependency resolution|npm ERR|pip.*resolution", .88), (Category.CONFIGURATION_ERROR, r"missing environment|configuration missing|invalid configuration", .86), (Category.DATABASE_MIGRATION_ERROR, r"migration failed|relation does not exist|SQL error|database.*refused", .88), (Category.CONTAINER_ERROR, r"Docker build failed|failed to build image|container exited", .90), (Category.AUTHORIZATION_ERROR, r"unauthorized|forbidden|permission denied|HTTP 40[13]", .91), (Category.NETWORK_TIMEOUT, r"timeout|DNS failure|connection reset|network unreachable", .87), (Category.DEPLOYMENT_ERROR, r"deploy(ment)? failed|release failed|rollout", .82)]

def analyze(cleaned_log: str, evidence: list[str]):
    scores=[]
    for category, pattern, confidence in RULES:
        hits=[line for line in evidence if re.search(pattern,line,re.I)]
        if hits: scores.append((len(hits)*confidence, category, confidence, hits))
    if not scores: return {"category":Category.UNKNOWN.value,"confidence":.25,"severity":Severity.LOW.value,"summary":"The workflow failed without a recognized signature.","root_cause":"Insufficient diagnostic evidence to identify a specific root cause.","failed_step":"Unknown","evidence":evidence[:10],"suggested_actions":[{"description":"Review the failed step and expand the log context.","priority":1}]}
    _, category, base, hits=max(scores,key=lambda item:item[0])
    severity=Severity.CRITICAL.value if category in (Category.DATABASE_MIGRATION_ERROR,Category.DEPLOYMENT_ERROR) else Severity.HIGH.value if base >= .9 else Severity.MEDIUM.value
    label=category.value.replace("_"," ").title()
    return {"category":category.value,"confidence":min(.99, base + min(.06,len(hits)*.01)),"severity":severity,"summary":f"{label} detected from workflow evidence.","root_cause":f"The log contains signatures associated with {label.lower()}.","failed_step":next((x for x in hits if "step" in x.lower()),"Workflow execution"),"evidence":hits[:10],"suggested_actions":[{"description":f"Inspect and remediate the {label.lower()} reported in the evidence.","priority":1},{"description":"Re-run the workflow after applying the fix.","priority":2}]}
