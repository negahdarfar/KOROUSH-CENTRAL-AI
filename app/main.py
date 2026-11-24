import secrets
from fastapi import FastAPI, HTTPException, Header
from .config import settings
from .github_client import GitHubClient
from .agent import summarize_audit

app = FastAPI(title="KOROUSH CENTRAL AI", version="0.1.1", description="Private, audit-first GitHub engineering agent")
gh = GitHubClient()

def require_admin(x_admin_key: str | None):
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    if not x_admin_key or not secrets.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "KOROUSH CENTRAL AI"}

@app.get("/api/github/repos")
async def repositories(x_admin_key: str | None = Header(default=None)):
    require_admin(x_admin_key)
    try:
        return {"repositories": await gh.list_repositories()}
    except Exception:
        raise HTTPException(status_code=502, detail="GitHub API request failed; check server logs")

@app.get("/api/audit/{owner}/{repo}")
async def audit(owner: str, repo: str, x_admin_key: str | None = Header(default=None)):
    require_admin(x_admin_key)
    full_name = f"{owner}/{repo}"
    try:
        inventory = await gh.get_repo_tree(full_name)
        report = await summarize_audit({"repository": full_name, "inventory": inventory})
        return {"repository": full_name, "mode": "read-only", "inventory": inventory, "report_fa": report}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception:
        raise HTTPException(status_code=502, detail="Audit failed; check server logs")
