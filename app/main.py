import secrets
import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
from .config import settings
from .github_client import GitHubClient
from .agent import summarize_audit, generate_fix_proposal

app = FastAPI(title="KOROUSH CENTRAL AI", version="0.2.0", description="Private, audit-first GitHub engineering agent")


class FixProposalRequest(BaseModel):
    task: str = Field(min_length=8, max_length=4000)
gh = GitHubClient()


def require_admin(x_admin_key: str | None):
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    if not x_admin_key or not secrets.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "KOROUSH CENTRAL AI"}


@app.get("/panel", response_class=HTMLResponse)
async def panel():
    return HTMLResponse("""<!doctype html>
<html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KOROUSH CENTRAL AI</title>
<style>
body{font-family:system-ui;background:#101827;color:#eef2ff;max-width:680px;margin:32px auto;padding:18px}
main{background:#1c293b;border:1px solid #34445c;border-radius:16px;padding:20px}
input,textarea,button{box-sizing:border-box;width:100%;padding:13px;margin:8px 0;border-radius:9px;font-size:16px}
input,textarea{background:#0d1726;color:white;border:1px solid #52647e}
textarea{min-height:100px}button{background:#2563eb;color:white;border:0;font-weight:700}
pre{white-space:pre-wrap;word-break:break-word;background:#0d1726;padding:14px;border-radius:9px;min-height:50px}
small{color:#b9c6d8}
</style><main><h2>KOROUSH CENTRAL AI</h2>
<p>کلید مدیریتی فقط در حافظه موقت همین صفحه نگهداری می‌شود و با بستن صفحه از بین می‌رود.</p>
<input id="key" type="password" autocomplete="off" placeholder="ADMIN_API_KEY">
<button id="check">آزمایش اتصال GitHub و مدل هوش مصنوعی</button>
<pre id="result">آماده آزمایش</pre>
<hr><h3>پیشنهاد اصلاح کد با هوش مصنوعی</h3>
<input id="owner" value="negahdarfar" placeholder="GitHub owner">
<input id="repo" placeholder="نام مخزن">
<textarea id="task" placeholder="شرح دقیق خطا یا اصلاح موردنیاز (حداقل ۸ نویسه)"></textarea>
<button id="propose">تحلیل و تولید پیشنهاد اصلاح (بدون اعمال تغییر)</button>
<pre id="proposal">ابتدا اتصال را آزمایش کنید.</pre>
<small>پیشنهادها فقط نمایش داده می‌شوند؛ هیچ فایلی خودکار تغییر نمی‌کند. پس از پایان، صفحه را ببندید.</small></main>
<script>
let adminKey='';
document.getElementById('check').addEventListener('click',async()=>{
 const key=document.getElementById('key').value;
 const out=document.getElementById('result');
 if(!key){out.textContent='لطفاً کلید مدیریتی را وارد کنید.';return;}
 adminKey=key;out.textContent='در حال بررسی...';
 try{
  const r=await fetch('/api/diagnostics',{headers:{'X-Admin-Key':adminKey}});
  const data=await r.json();out.textContent=JSON.stringify(data,null,2);
  if(r.status===401){adminKey='';out.textContent='کلید پذیرفته نشد. مقدار ADMIN_API_KEY در Railway را بررسی کنید.';}
 }catch(e){out.textContent='ارتباط برقرار نشد: '+e.message;}
 document.getElementById('key').value='';
});
document.getElementById('propose').addEventListener('click',async()=>{
 const owner=document.getElementById('owner').value.trim();
 const repo=document.getElementById('repo').value.trim();
 const task=document.getElementById('task').value.trim();
 const out=document.getElementById('proposal');
 if(!adminKey){out.textContent='ابتدا کلید مدیریتی را وارد و اتصال را آزمایش کنید.';return;}
 if(!owner||!repo||task.length<8){out.textContent='نام مالک، مخزن و شرح درخواست را کامل کنید.';return;}
 out.textContent='در حال تحلیل کد و ساخت پیشنهاد...';
 try{
  const url='/api/fix-proposal/'+encodeURIComponent(owner)+'/'+encodeURIComponent(repo);
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Key':adminKey},body:JSON.stringify({task})});
  const data=await r.json();out.textContent=JSON.stringify(data,null,2);
 }catch(e){out.textContent='خطا در ارتباط: '+e.message;}
});
</script></html>""")


@app.get("/api/diagnostics")
async def diagnostics(x_admin_key: str | None = Header(default=None)):
    require_admin(x_admin_key)
    result = {
        "service": "ok",
        "github": {"status": "not_checked"},
        "llm": {"status": "not_checked"},
    }

    try:
        repos = await gh.list_repositories()
        result["github"] = {"status": "ok", "repository_count": len(repos)}
    except Exception:
        result["github"] = {"status": "error", "message": "GitHub API check failed; verify GITHUB_TOKEN and its permissions"}

    llm = settings.active_llm
    if not all(llm[key] for key in ("base_url", "api_key", "model")):
        result["llm"] = {
            "status": "not_configured",
            "provider": llm["provider"],
            "message": "Configure the selected provider's API key and model in Railway variables",
        }
    else:
        try:
            url = llm["base_url"] + "/chat/completions"
            payload = {
                "model": llm["model"],
                "messages": [{"role": "user", "content": "Reply with OK"}],
                "max_tokens": 5,
                "temperature": 0,
            }
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {llm['api_key']}"},
                    json=payload,
                )
                response.raise_for_status()
                response.json()
            result["llm"] = {"status": "ok", "provider": llm["provider"], "model": llm["model"]}
        except Exception:
            result["llm"] = {"status": "error", "provider": llm["provider"], "message": "LLM request failed; verify provider, key, model and available quota"}

    return result


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
        inventory = await gh.get_repo_snapshot(full_name)
        report = await summarize_audit({"repository": full_name, "inventory": inventory})
        return {"repository": full_name, "mode": "read-only", "inventory": {"default_branch": inventory["default_branch"], "truncated": inventory["truncated"], "file_count": inventory["file_count"], "files": [{"path": item["path"], "characters_analyzed": len(item["content"])} for item in inventory["files"]]}, "report_fa": report}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception:
        raise HTTPException(status_code=502, detail="Audit failed; check server logs")


@app.post("/api/fix-proposal/{owner}/{repo}")
async def fix_proposal(
    owner: str,
    repo: str,
    request: FixProposalRequest,
    x_admin_key: str | None = Header(default=None),
):
    """Generate a bounded AI repair proposal; never write to GitHub."""
    require_admin(x_admin_key)
    full_name = f"{owner}/{repo}"
    try:
        snapshot = await gh.get_repo_snapshot(full_name)
        proposal = await generate_fix_proposal(full_name, request.task, snapshot)
        return {
            "repository": full_name,
            "mode": "proposal-only",
            "applied": False,
            "snapshot": {
                "default_branch": snapshot["default_branch"],
                "file_count": snapshot["file_count"],
                "paths": [item["path"] for item in snapshot["files"]],
            },
            "proposal": proposal,
        }
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="Fix proposal failed; check server logs")
