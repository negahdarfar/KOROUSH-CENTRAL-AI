import secrets
import httpx
from fastapi import FastAPI, HTTPException, Header, Query
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
from .config import settings
from .github_client import GitHubClient
from .agent import summarize_audit, generate_fix_proposal
from .avalai import list_avalai_models
from .avalai_gateway import CAPABILITY_CATALOG, JSON_SURFACES, execute_avalai_surface, AvalAIRequestError

app = FastAPI(title="KOROUSH CENTRAL AI", version="0.3.0", description="Private, audit-first GitHub engineering agent")


class FixProposalRequest(BaseModel):
    task: str = Field(min_length=8, max_length=4000)
    model: str | None = Field(default=None, min_length=1, max_length=200)


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
input,textarea,button,select{box-sizing:border-box;width:100%;padding:13px;margin:8px 0;border-radius:9px;font-size:16px}
input,textarea,select{background:#0d1726;color:white;border:1px solid #52647e}
textarea{min-height:100px}button{background:#2563eb;color:white;border:0;font-weight:700}
pre{white-space:pre-wrap;word-break:break-word;background:#0d1726;padding:14px;border-radius:9px;min-height:50px}
small{color:#b9c6d8}
</style><main><h2>KOROUSH CENTRAL AI</h2>
<p>کلید مدیریتی فقط در حافظه موقت همین صفحه نگهداری می‌شود و با بستن صفحه از بین می‌رود.</p>
<input id="key" type="password" autocomplete="off" placeholder="ADMIN_API_KEY">
<button id="check">آزمایش اتصال GitHub و مدل هوش مصنوعی</button>
<pre id="result">آماده آزمایش</pre>
<hr><h3>مدل هوش مصنوعی AvalAI</h3>
<button id="loadModels">دریافت فهرست مدل‌های مجاز حساب AvalAI</button>
<select id="model"><option value="">مدل پیش‌فرض Railway</option></select>
<small id="modelInfo">پس از دریافت فهرست، مدل موردنظر را انتخاب کنید. برای کارهای متنی، مدل‌های chat مناسب‌اند.</small>
<hr><h3>پیشنهاد اصلاح کد با هوش مصنوعی</h3>
<input id="owner" value="negahdarfar" placeholder="GitHub owner">
<input id="repo" placeholder="نام مخزن">
<textarea id="task" placeholder="شرح دقیق خطا یا اصلاح موردنیاز (حداقل ۸ نویسه)"></textarea>
<button id="propose">تحلیل و تولید پیشنهاد اصلاح (بدون اعمال تغییر)</button>
<pre id="proposal">ابتدا اتصال را آزمایش کنید.</pre>
<small>پیشنهادها فقط نمایش داده می‌شوند؛ هیچ فایلی خودکار تغییر نمی‌کند. پس از پایان، صفحه را ببندید.</small></main>
<script>
let adminKey='';
const headers=()=>({'X-Admin-Key':adminKey});
document.getElementById('check').addEventListener('click',async()=>{
 const key=document.getElementById('key').value;
 const out=document.getElementById('result');
 if(!key){out.textContent='لطفاً کلید مدیریتی را وارد کنید.';return;}
 adminKey=key;out.textContent='در حال بررسی...';
 try{
  const r=await fetch('/api/diagnostics',{headers:headers()});
  const data=await r.json();out.textContent=JSON.stringify(data,null,2);
  if(r.status===401){adminKey='';out.textContent='کلید پذیرفته نشد. مقدار ADMIN_API_KEY در Railway را بررسی کنید.';}
 }catch(e){out.textContent='ارتباط برقرار نشد: '+e.message;}
 document.getElementById('key').value='';
});
document.getElementById('loadModels').addEventListener('click',async()=>{
 const out=document.getElementById('modelInfo');
 if(!adminKey){out.textContent='ابتدا اتصال را آزمایش کنید.';return;}
 out.textContent='در حال دریافت فهرست و مشخصات مدل‌ها...';
 try{
  const r=await fetch('/api/avalai/models',{headers:headers()});
  const data=await r.json();
  if(!r.ok)throw new Error(data.detail||'خطا در دریافت مدل‌ها');
  const select=document.getElementById('model');
  select.innerHTML='<option value="">مدل پیش‌فرض Railway</option>';
  for(const item of data.models){
   const option=document.createElement('option');
   option.value=item.id;
   option.textContent=item.id+' — '+(item.mode||'نوع نامشخص');
   select.appendChild(option);
  }
  out.textContent='تعداد مدل‌های قابل مشاهده: '+data.count+'؛ فقط مدل‌های chat برای تحلیل و پیشنهاد اصلاح متنی مناسب‌اند.';
 }catch(e){out.textContent='دریافت فهرست مدل‌ها ناموفق بود: '+e.message;}
});
document.getElementById('propose').addEventListener('click',async()=>{
 const owner=document.getElementById('owner').value.trim();
 const repo=document.getElementById('repo').value.trim();
 const task=document.getElementById('task').value.trim();
 const model=document.getElementById('model').value;
 const out=document.getElementById('proposal');
 if(!adminKey){out.textContent='ابتدا کلید مدیریتی را وارد و اتصال را آزمایش کنید.';return;}
 if(!owner||!repo||task.length<8){out.textContent='نام مالک، مخزن و شرح درخواست را کامل کنید.';return;}
 out.textContent='در حال تحلیل کد و ساخت پیشنهاد...';
 try{
  const url='/api/fix-proposal/'+encodeURIComponent(owner)+'/'+encodeURIComponent(repo);
  const body={task};if(model)body.model=model;
  const r=await fetch(url,{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify(body)});
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


@app.get("/api/avalai/models")
async def avalai_models(x_admin_key: str | None = Header(default=None)):
    require_admin(x_admin_key)
    try:
        models = await list_avalai_models()
        return {"provider": "avalai", "count": len(models), "models": models}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"AvalAI catalog request failed with HTTP {exc.response.status_code}")
    except Exception:
        raise HTTPException(status_code=502, detail="AvalAI model catalog request failed")


@app.get("/api/github/repos")
async def repositories(x_admin_key: str | None = Header(default=None)):
    require_admin(x_admin_key)
    try:
        return {"repositories": await gh.list_repositories()}
    except Exception:
        raise HTTPException(status_code=502, detail="GitHub API request failed; check server logs")


@app.get("/api/audit/{owner}/{repo}")
async def audit(owner: str, repo: str, x_admin_key: str | None = Header(default=None), model: str | None = Query(default=None)):
    require_admin(x_admin_key)
    full_name = f"{owner}/{repo}"
    try:
        inventory = await gh.get_repo_snapshot(full_name)
        report = await summarize_audit({"repository": full_name, "inventory": inventory}, model=model)
        return {"repository": full_name, "mode": "read-only", "model": model or settings.active_llm["model"], "inventory": {"default_branch": inventory["default_branch"], "truncated": inventory["truncated"], "file_count": inventory["file_count"], "files": [{"path": item["path"], "characters_analyzed": len(item["content"])} for item in inventory["files"]]}, "report_fa": report}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
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
        proposal = await generate_fix_proposal(full_name, request.task, snapshot, model=request.model)
        return {
            "repository": full_name,
            "mode": "proposal-only",
            "applied": False,
            "model": request.model or settings.active_llm["model"],
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


class AvalAIExecuteRequest(BaseModel):
    payload: dict = Field(min_length=1)


@app.get("/api/avalai/capabilities")
async def avalai_capabilities(x_admin_key: str | None = Header(default=None)):
    """List documented API surfaces and clearly label transport requirements."""
    require_admin(x_admin_key)
    return {
        "provider": "avalai",
        "json_surfaces": len(JSON_SURFACES),
        "capabilities": CAPABILITY_CATALOG,
        "notes": [
            "The catalog describes documented API routes, not proof that every route/model is enabled for this account.",
            "Every execution is checked against the authenticated model catalog when a model ID is supplied.",
            "Multipart uploads, batch file workflows and realtime sessions need dedicated transports and are not sent through the JSON gateway.",
        ],
    }


@app.post("/api/avalai/execute/{surface}")
async def avalai_execute(
    surface: str,
    request: AvalAIExecuteRequest,
    x_admin_key: str | None = Header(default=None),
):
    """Execute an allow-listed AvalAI JSON capability; no arbitrary URL forwarding."""
    require_admin(x_admin_key)
    if surface not in JSON_SURFACES:
        raise HTTPException(status_code=404, detail="Unknown or non-JSON AvalAI capability")
    try:
        return await execute_avalai_surface(surface, request.payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except AvalAIRequestError as exc:
        raise HTTPException(status_code=502, detail={"provider_status": exc.status_code, "provider_error": exc.detail})
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="AvalAI request failed; check route, model access, quota and network")
