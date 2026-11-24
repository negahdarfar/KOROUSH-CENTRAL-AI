import secrets
import asyncio
import httpx
from fastapi import FastAPI, HTTPException, Header, Query
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
from .config import settings
from .github_client import GitHubClient
from .agent import summarize_audit, generate_fix_proposal, generate_fix_implementation, editable_snapshot_paths, validate_fix_implementation, build_approval_digest
from .github_writer import publish_changes
from .avalai import list_avalai_models, list_avalai_model_catalog
from .model_router import select_avalai_model
from .avalai_gateway import CAPABILITY_CATALOG, JSON_SURFACES, execute_avalai_surface, AvalAIRequestError
from .version import runtime_version

app = FastAPI(title="KOROUSH CENTRAL AI", version="0.3.0", description="Private, audit-first GitHub engineering agent")


class FixProposalRequest(BaseModel):
    task: str = Field(min_length=8, max_length=4000)
    model: str | None = Field(default=None, min_length=1, max_length=200)



class FixApplyRequest(BaseModel):
    task: str = Field(min_length=8, max_length=4000)
    confirm: bool = False
    approved_implementation: dict | None = None
    source_shas: dict[str, str] | None = None
    approval_digest: str | None = Field(default=None, min_length=64, max_length=64)


gh = GitHubClient()


def require_admin(x_admin_key: str | None):
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    if not x_admin_key or not secrets.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "KOROUSH CENTRAL AI"}


@app.get("/api/version")
async def api_version():
    """Expose non-secret runtime commit and deployment metadata for verification."""
    return runtime_version()


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
<section id="deploymentVersion" style="border:1px solid #52647e;border-radius:10px;padding:12px;margin:14px 0">
<strong>نسخه مستقرشده Railway</strong>
<p id="versionStatus">در حال دریافت اطلاعات نسخه...</p>
<small id="versionDetails">این بخش فقط اطلاعات غیرمحرمانه نسخه و Deployment را نمایش می‌دهد.</small>
</section>
<p>کلید مدیریتی فقط در حافظه موقت همین صفحه نگهداری می‌شود و با بستن صفحه از بین می‌رود.</p>
<input id="key" type="password" autocomplete="off" placeholder="ADMIN_API_KEY">
<button id="check">آزمایش اتصال GitHub و مدل هوش مصنوعی</button>
<pre id="result">آماده آزمایش</pre>
<hr><h3>مدل هوش مصنوعی AvalAI</h3>
<button id="loadModels">دریافت فهرست مدل‌های مجاز حساب AvalAI</button>
<select id="model"><option value="">مدل پیش‌فرض Railway</option></select>
<small id="modelInfo">پس از دریافت فهرست، مدل موردنظر را انتخاب کنید. برای کارهای متنی، مدل‌های chat مناسب‌اند.</small>
<hr><h3>درگاه چندقابلیتی AvalAI</h3>
<p>از فهرست زیر یک API را انتخاب و بدنه JSON متناسب با مستندات همان قابلیت را ارسال کنید. مدل انتخابی باید در فهرست مجاز حساب باشد.</p>
<select id="surface">
<option value="responses">Responses / استدلال و چندرسانه‌ای</option>
<option value="chat_completions">Chat Completions / چت و بینایی</option>
<option value="decisions">Decisions / تصمیم‌گیری</option>
<option value="systemone">System One</option>
<option value="extraction">Extraction / استخراج داده</option>
<option value="embeddings">Embeddings / بردارسازی</option>
<option value="images_generations">Image Generation / تولید تصویر</option>
<option value="audio_speech">Text to Speech / تولید گفتار</option>
<option value="moderations">Moderation / ایمنی محتوا</option>
<option value="rerank">Rerank / رتبه‌بندی نتایج</option>
<option value="ocr">OCR / تشخیص متن تصویر</option>
<option value="videos">Video / عملیات ویدئویی</option>
</select>
<textarea id="apiPayload">{ "input": "Hello" }</textarea>
<button id="runCapability">اجرای API انتخاب‌شده</button>
<pre id="capabilityResult">ابتدا مدل‌ها را بارگذاری کنید؛ سپس بدنه درخواست را مطابق مستندات تنظیم کنید.</pre>
<p><small>قابلیت‌های صوتی ورودی، ویرایش تصویر، فایل و Batch به بارگذاری multipart یا انتقال زنده نیاز دارند و هنوز از این درگاه JSON اجرا نمی‌شوند.</small></p>
<hr><h3>پیشنهاد اصلاح کد با هوش مصنوعی</h3>
<input id="owner" value="negahdarfar" placeholder="GitHub owner">
<input id="repo" placeholder="نام مخزن">
<textarea id="task" placeholder="شرح دقیق خطا یا اصلاح موردنیاز (حداقل ۸ نویسه)"></textarea>
<button id="propose">تحلیل و آماده‌سازی اصلاحات پیشنهادی</button>
<pre id="proposal">ابتدا اتصال را آزمایش کنید.</pre>
<label><input id="confirmApply" type="checkbox" style="width:auto"> تأیید می‌کنم اصلاحات روی شاخه جدید GitHub ثبت و Pull Request آزمایشی ساخته شود.</label>
<button id="applyFix">تأیید و ایجاد شاخه + Draft Pull Request</button>
<pre id="applyResult">هیچ تغییری بدون تأیید صریح شما ثبت نمی‌شود.</pre>
<small>شاخه اصلی هرگز مستقیماً تغییر نمی‌کند و Pull Request به‌صورت Draft ساخته می‌شود؛ ادغام خودکار انجام نمی‌شود.</small></main>
<script>
let adminKey='';
let pendingFixPreview=null;
async function loadDeploymentVersion(){
 const status=document.getElementById('versionStatus');
 const details=document.getElementById('versionDetails');
 try{
  const response=await fetch('/api/version',{cache:'no-store'});
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail||'خطا در دریافت نسخه');
  if(data.commit_sha){
   status.textContent='Commit مستقرشده: '+data.commit_short+' — '+(data.branch||'شاخه نامشخص');
   details.textContent='SHA کامل: '+data.commit_sha+
    (data.deployment_id?' | Deployment: '+data.deployment_id:'')+
    (data.environment?' | محیط: '+data.environment:'')+
    ' | برای تأیید نهایی، SHA را با آخرین Commit شاخه main در GitHub مقایسه کنید.';
  }else{
   status.textContent='نسخه دقیق قابل تشخیص نیست؛ متغیر RAILWAY_GIT_COMMIT_SHA در محیط اجرا موجود نیست.';
   details.textContent='سرویس پاسخ می‌دهد، اما برای نمایش SHA باید متادیتای Railway در زمان اجرا در دسترس باشد.';
  }
 }catch(error){
  status.textContent='بررسی نسخه ناموفق بود: '+error.message;
 }
}
loadDeploymentVersion();

const headers=()=>({'X-Admin-Key':adminKey});
document.getElementById('check').addEventListener('click',async()=>{
 const key=document.getElementById('key').value;
 const out=document.getElementById('result');
 if(!key){out.textContent='لطفاً کلید مدیریتی را وارد کنید.';return;}
 adminKey=key;out.textContent='در حال بررسی...';
 try{
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),90000);
  let r;
  const chosenModel=document.getElementById('model').value;
  const diagnosticsUrl=new URL('/api/diagnostics',window.location.origin);
  if(chosenModel)diagnosticsUrl.searchParams.set('model',chosenModel);
  try{r=await fetch(diagnosticsUrl.toString(),{headers:headers(),signal:controller.signal});}
  finally{clearTimeout(timer);}
  const data=await r.json();out.textContent=JSON.stringify(data,null,2);
  if(r.status===401){adminKey='';out.textContent='کلید پذیرفته نشد. مقدار ADMIN_API_KEY در Railway را بررسی کنید.';}
 }catch(e){out.textContent=e.name==='AbortError'?'زمان بررسی تمام شد؛ سرویس یا یکی از اتصال‌های خارجی پاسخ نداد. لطفاً دوباره بعد از بررسی لاگ‌ها تلاش کنید.':'ارتباط برقرار نشد: '+e.message;}
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
document.getElementById('runCapability').addEventListener('click',async()=>{
 const surface=document.getElementById('surface').value;
 const out=document.getElementById('capabilityResult');
 if(!adminKey){out.textContent='ابتدا اتصال مدیریتی را آزمایش کنید.';return;}
 let payload;
 try{payload=JSON.parse(document.getElementById('apiPayload').value);}
 catch(e){out.textContent='JSON نامعتبر است: '+e.message;return;}
 const selected=document.getElementById('model').value;
 if(selected)payload.model=selected;
 out.textContent='در حال ارسال درخواست به AvalAI...';
 try{
  const r=await fetch('/api/avalai/execute/'+encodeURIComponent(surface),{
   method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({payload})
  });
  const data=await r.json();out.textContent=JSON.stringify(data,null,2);
 }catch(e){out.textContent='خطا در درخواست: '+e.message;}
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
  const url='/api/fix-preview/'+encodeURIComponent(owner)+'/'+encodeURIComponent(repo);
  const body={task};if(model)body.model=model;
  const r=await fetch(url,{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await r.json();if(!r.ok)throw new Error(data.detail||'Preview failed');
  pendingFixPreview={repository:owner+'/'+repo,task,preview:data};
  out.textContent=JSON.stringify(data,null,2);
  document.getElementById('applyResult').textContent=data.approval_digest?'پیش‌نمایش آماده است؛ تمام محتوای فایل‌ها را بررسی کنید.':'تغییری برای انتشار پیشنهاد نشده است.';
 }catch(e){out.textContent='خطا در ارتباط: '+e.message;}
});
document.getElementById('applyFix').addEventListener('click',async()=>{
 const owner=document.getElementById('owner').value.trim(), repo=document.getElementById('repo').value.trim(), task=document.getElementById('task').value.trim();
 const out=document.getElementById('applyResult');
 if(!adminKey){out.textContent='ابتدا اتصال مدیریتی را آزمایش کنید.';return;}
 if(!pendingFixPreview||pendingFixPreview.repository!==owner+'/'+repo||pendingFixPreview.task!==task){out.textContent='پیش‌نمایش با درخواست جاری مطابقت ندارد؛ پیش‌نمایش جدید بسازید.';return;}
 const preview=pendingFixPreview.preview;
 if(!preview.approval_digest){out.textContent='پیش‌نمایش قابل انتشار نیست یا تغییری ندارد.';return;}
 if(!document.getElementById('confirmApply').checked){out.textContent='پس از بررسی دقیق پیش‌نمایش، تأیید را فعال کنید.';return;}
 if(!confirm('آیا دقیقاً همین نسخه کامل فایل‌ها را تأیید می‌کنید؟'))return;
 out.textContent='در حال بررسی نسخه مبدأ و ثبت همان پیش‌نمایش...';
 try{
  const body={task,confirm:true,approved_implementation:preview.implementation,source_shas:preview.source_shas,approval_digest:preview.approval_digest};
  const r=await fetch('/api/fix-apply/'+encodeURIComponent(owner)+'/'+encodeURIComponent(repo),{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await r.json();out.textContent=JSON.stringify(data,null,2);
  if(r.ok&&data.applied){pendingFixPreview=null;document.getElementById('confirmApply').checked=false;}
 }catch(e){out.textContent='خطا در اجرای اصلاح: '+e.message;}
});
</script></html>""")


@app.get("/api/diagnostics")
async def diagnostics(
    x_admin_key: str | None = Header(default=None),
    model: str | None = Query(default=None, min_length=1, max_length=200),
):
    require_admin(x_admin_key)
    clock = asyncio.get_running_loop()
    started = clock.time()
    result = {
        "service": "ok",
        "github": {"status": "not_checked"},
        "llm": {"status": "not_checked"},
    }

    try:
        repos = await asyncio.wait_for(gh.list_repositories(), timeout=15)
        result["github"] = {"status": "ok", "repository_count": len(repos)}
    except asyncio.TimeoutError:
        result["github"] = {"status": "timeout", "message": "GitHub check exceeded 15 seconds"}
    except Exception:
        result["github"] = {"status": "error", "message": "GitHub API check failed; verify GITHUB_TOKEN and its permissions"}

    llm = settings.active_llm
    required = ("base_url", "api_key") if llm["provider"] == "avalai" else ("base_url", "api_key", "model")
    if not all(llm[key] for key in required):
        result["llm"] = {
            "status": "not_configured",
            "provider": llm["provider"],
            "message": "Configure the provider base URL and API key; AVALAI_MODEL is optional when using AvalAI",
        }
    else:
        selected_model = model or llm["model"]
        model_selection = "request" if model else ("configured" if llm["model"] else "catalog_auto")
        phase = "catalog"
        catalog_ms = None
        chat_ms = None
        try:
            if llm["provider"] == "avalai":
                catalog_started = clock.time()
                catalog = await asyncio.wait_for(list_avalai_model_catalog(), timeout=15)
                catalog_ms = round((clock.time() - catalog_started) * 1000)
                available_models = {item["id"] for item in catalog}
                if selected_model and selected_model not in available_models:
                    raise ValueError("Requested model is not available to this AvalAI API key")
                if not selected_model:
                    selected_model = select_avalai_model(catalog, task="fast")
                if not selected_model:
                    raise ValueError("No chat-capable model was selected from the AvalAI catalog")

            phase = "chat_completion"
            url = llm["base_url"].rstrip("/") + "/chat/completions"
            payload = {
                "model": selected_model,
                "messages": [{"role": "user", "content": "Reply with OK"}],
                "max_tokens": 5,
                "temperature": 0,
            }
            chat_started = clock.time()
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=8.0)) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {llm['api_key']}"},
                    json=payload,
                )
                response.raise_for_status()
                response.json()
            chat_ms = round((clock.time() - chat_started) * 1000)
            result["llm"] = {
                "status": "ok",
                "provider": llm["provider"],
                "model": selected_model,
                "model_selection": model_selection,
                "phase": "complete",
                "timings_ms": {"catalog": catalog_ms, "chat_completion": chat_ms, "total": round((clock.time() - started) * 1000)},
            }
        except asyncio.TimeoutError:
            result["llm"] = {
                "status": "timeout", "provider": llm["provider"],
                "model": selected_model or None, "phase": phase,
                "message": "AvalAI model catalog check exceeded 15 seconds" if phase == "catalog" else "LLM request exceeded its 60-second timeout",
                "timings_ms": {"catalog": catalog_ms, "chat_completion": chat_ms, "total": round((clock.time() - started) * 1000)},
            }
        except httpx.TimeoutException:
            result["llm"] = {
                "status": "timeout", "provider": llm["provider"],
                "model": selected_model or None, "phase": phase,
                "message": "AvalAI model catalog request timed out" if phase == "catalog" else "LLM chat completion exceeded 60 seconds",
                "timings_ms": {"catalog": catalog_ms, "chat_completion": chat_ms, "total": round((clock.time() - started) * 1000)},
            }
        except ValueError as exc:
            result["llm"] = {
                "status": "error", "provider": llm["provider"],
                "model": selected_model or None, "phase": phase, "message": str(exc),
                "timings_ms": {"catalog": catalog_ms, "chat_completion": chat_ms, "total": round((clock.time() - started) * 1000)},
            }
        except httpx.HTTPStatusError as exc:
            result["llm"] = {
                "status": "error", "provider": llm["provider"],
                "model": selected_model or None, "phase": phase,
                "provider_status": exc.response.status_code,
                "message": "AvalAI rejected the request; check model access, key and quota",
                "timings_ms": {"catalog": catalog_ms, "chat_completion": chat_ms, "total": round((clock.time() - started) * 1000)},
            }
        except Exception:
            result["llm"] = {
                "status": "error", "provider": llm["provider"],
                "model": selected_model or None, "phase": phase,
                "message": "LLM request failed; verify provider, key, model and available quota",
                "timings_ms": {"catalog": catalog_ms, "chat_completion": chat_ms, "total": round((clock.time() - started) * 1000)},
            }

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
        return {"repository": full_name, "mode": "read-only", "model": model or settings.active_llm["model"] or "catalog_auto", "inventory": {"default_branch": inventory["default_branch"], "truncated": inventory["truncated"], "file_count": inventory["file_count"], "files": [{"path": item["path"], "characters_analyzed": len(item["content"])} for item in inventory["files"]]}, "report_fa": report}
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
            "model": request.model or settings.active_llm["model"] or "catalog_auto",
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


@app.post("/api/fix-preview/{owner}/{repo}")
async def fix_preview(owner: str, repo: str, request: FixProposalRequest, x_admin_key: str | None = Header(default=None)):
    """Create a non-writing preview bound to exact source file versions."""
    require_admin(x_admin_key)
    full_name = f"{owner}/{repo}"
    try:
        snapshot = await gh.get_repo_snapshot(full_name)
        implementation = await generate_fix_implementation(full_name, request.task, snapshot, model=request.model)
        if not implementation["files"]:
            return {"repository": full_name, "mode": "preview_only_no_changes", "applied": False, "implementation": implementation, "source_shas": {}, "approval_digest": None}
        by_path = {item["path"]: item.get("source_sha") for item in snapshot["files"]}
        source_shas = {}
        for item in implementation["files"]:
            source_sha = by_path.get(item["path"])
            if not source_sha:
                raise ValueError(f"Could not bind preview to current GitHub file version: {item['path']}")
            source_shas[item["path"]] = source_sha
        digest = build_approval_digest(full_name, request.task, implementation, source_shas)
        return {"repository": full_name, "mode": "preview_only", "applied": False, "model": implementation["model"],
                "snapshot": {"default_branch": snapshot["default_branch"], "file_count": snapshot["file_count"],
                             "paths": [item["path"] for item in snapshot["files"]]},
                "implementation": implementation, "source_shas": source_shas, "approval_digest": digest,
                "approval_note": "Review the exact file contents; submit this unchanged preview only after approval."}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=502, detail="Fix preview failed; check service logs")


@app.post("/api/fix-apply/{owner}/{repo}")
async def fix_apply(
    owner: str,
    repo: str,
    request: FixApplyRequest,
    x_admin_key: str | None = Header(default=None),
):
    """Publish only the exact reviewed preview after explicit confirmation."""
    require_admin(x_admin_key)
    if request.confirm is not True:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required before writing to GitHub")
    if not request.approved_implementation or not request.source_shas or not request.approval_digest:
        raise HTTPException(status_code=400, detail="A reviewed preview, source versions and approval digest are required")
    full_name = f"{owner}/{repo}"
    try:
        snapshot = await gh.get_repo_snapshot(full_name)
        implementation = validate_fix_implementation(request.approved_implementation, editable_snapshot_paths(snapshot))
        expected_paths = {item["path"] for item in implementation["files"]}
        if not expected_paths or set(request.source_shas) != expected_paths:
            raise ValueError("Approved source version map does not match reviewed files")
        current_shas = {item["path"]: item.get("source_sha") for item in snapshot["files"]}
        for path, approved_sha in request.source_shas.items():
            if not approved_sha or current_shas.get(path) != approved_sha:
                raise ValueError(f"Source file changed after preview; create a new preview: {path}")
        digest = build_approval_digest(full_name, request.task, implementation, request.source_shas)
        if not secrets.compare_digest(digest, request.approval_digest):
            raise ValueError("Approval digest does not match the exact reviewed implementation")
        for item in implementation["files"]:
            item["source_sha"] = request.source_shas[item["path"]]
        published = await publish_changes(full_name, implementation["files"], implementation["summary"],
                                          implementation["tests_to_run"], snapshot["default_branch"])
        return {"repository": full_name, "applied": True, "mode": "branch_and_draft_pull_request",
                "model": implementation.get("model"), "summary": implementation["summary"],
                "findings": implementation["findings"], "tests_to_run": implementation["tests_to_run"], **published}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"GitHub rejected the branch, commit, or pull request operation (HTTP {exc.response.status_code})")
    except Exception:
        raise HTTPException(status_code=502, detail="AI repair publishing failed; check service logs")


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
