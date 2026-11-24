from fastapi import FastAPI, HTTPException
from .config import settings
from .github_client import GitHubClient
from .agent import summarize_audit

app = FastAPI(title="KOROUSH CENTRAL AI", version="0.1.0", description="Private, audit-first GitHub engineering agent")
gh = GitHubClient()

@app.get("/health")
async def health():
    return {"status": "ok", "service": "KOROUSH CENTRAL AI"}

@app.get("/api/github/repos")
async def repositories():
    try:
        return {"repositories": await gh.list_repositories()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

@app.get("/api/audit/{owner}/{repo}")
async def audit(owner: str, repo: str):
    full_name = f"{owner}/{repo}"
    try:
        inventory = await gh.get_repo_tree(full_name)
        report = await summarize_audit({"repository": full_name, "inventory": inventory})
        return {"repository": full_name, "mode": "read-only", "inventory": inventory, "report_fa": report}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
