"""Opt-in repository reconciliation; never creates keys or changes repositories."""
import asyncio
import logging
import os
import httpx
from fastapi import APIRouter,Header,HTTPException
from .github_client import GitHubClient, API
from .mcp_gateway import admin,identity
from .repository_catalog import catalog,reconcile,capability_snapshot

router=APIRouter()
log=logging.getLogger(__name__)
lock=asyncio.Lock()

async def scan():
    # Bounded first 5 pages. No destructive reconciliation on partial scans.
    async with lock:
        items=[]
        async with httpx.AsyncClient(timeout=15,follow_redirects=False,trust_env=False) as client:
            for page in range(1,6):
                response=await client.get(API+"/user/repos",headers=GitHubClient()._headers(),params={"per_page":100,"page":page,"affiliation":"owner,collaborator,organization_member","sort":"updated"})
                response.raise_for_status()
                batch=response.json()
                if not isinstance(batch,list) or len(batch)>100: raise ValueError("Invalid GitHub inventory")
                items.extend(batch)
                if len(batch)<100: break
        result=await asyncio.to_thread(reconcile,items)
        return {"count":len(result),"scan_complete":len(batch)<100,"repositories":result}

@router.post("/api/admin/repositories/reconcile")
async def refresh(x_admin_key:str|None=Header(default=None)):
    admin(x_admin_key)
    try: return await scan()
    except (httpx.HTTPError,RuntimeError,ValueError): raise HTTPException(503,"Repository discovery unavailable")

@router.get("/api/admin/repositories/catalog")
async def inventory(x_admin_key:str|None=Header(default=None)):
    admin(x_admin_key)
    return {"repositories":await asyncio.to_thread(catalog)}

@router.get("/api/repositories/sync")
async def sync(repository:str,x_tenant_key:str|None=Header(default=None)):
    info=identity(x_tenant_key,repository,("registry:read",))
    return await asyncio.to_thread(capability_snapshot,repository,info["scopes"])

def enabled():
    return os.getenv("REPOSITORY_AUTO_DISCOVERY","false").lower() in {"true","1"}

async def discovery_loop():
    while True:
        try: await scan()
        except asyncio.CancelledError: raise
        except Exception: log.warning("Repository discovery failed; retaining last catalog")
        await asyncio.sleep(900)
