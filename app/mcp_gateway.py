"""Tenant-bound MCP gateway for reviewed in-process tools.

No discovered endpoint is executed. Registry entries remain metadata until a
reviewed transport and independently verified endpoint/tool pricing exist.
"""
from __future__ import annotations

import json
import os
import secrets
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import settings
from .tenant_auth import authenticate_tenant_key
from .extension_registry import register_extension, list_extensions, ExtensionRegistryError
from .source_connector_policy import validate_source_url, SourcePolicyError
from .schema_registry import validate_instance, SchemaValidationError
from .agent_registry import list_agents
from .worker_runtime import worker_ready
from .worker_heartbeat import worker_health
from .agent_contracts import validate_agent_input, AgentContractError
from .job_routes import JobSubmitRequest, submit_job, get_job_status
from .event_routes import PublishRequest, publish
from .discovery_routes import DiscoverySearchRequest, discover_resources

router = APIRouter()
PROTOCOL = "mcp-streamable-http"
VERSIONS = ("2025-03-26", "2025-06-18", "2025-11-25")
MAX_BODY = 64 * 1024
MAX_OUTPUT = 256 * 1024

def admin(key):
    if not settings.admin_api_key or not key or not secrets.compare_digest(key, settings.admin_api_key):
        raise HTTPException(401, "Valid X-Admin-Key is required")

def identity(key, repo, scopes=()):
    try:
        info = authenticate_tenant_key(key)
    except RuntimeError as exc:
        raise HTTPException(503, "Tenant authentication unavailable") from exc
    if not info:
        raise HTTPException(401, "Valid repository tenant key required")
    if repo.lower() not in info["repositories"] or not set(scopes).issubset(info["scopes"]):
        raise HTTPException(403, "Repository or scope not assigned")
    if repo.lower() not in {r.lower() for r in settings.repo_allowlist}:
        raise HTTPException(403, "Repository not approved by operator")
    return info

def servers(repo):
    rows = list_extensions(repository=repo, kind="tool")
    return [{"id":x["extension_id"],"version":x["version"],"name":x["name"],
             "capabilities":x["capabilities"],"execution":"blocked_unreviewed_transport",
             "price_status":"unverified","health":"not_probed"}
            for x in rows if x["protocol"] == PROTOCOL and x["repositories"]]

class ServerRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: dict

@router.post("/api/admin/mcp/servers", status_code=201)
async def register_server(request: ServerRegistration, x_admin_key: str | None = Header(default=None)):
    admin(x_admin_key)
    item = dict(request.manifest)
    try:
        if item.get("kind") != "tool" or item.get("protocol") != PROTOCOL or not item.get("repositories"):
            raise ValueError("MCP registration requires kind=tool, protocol=mcp-streamable-http and explicit repositories")
        endpoint = item.get("endpoint")
        host = urlsplit(endpoint or "").hostname
        if not host or urlsplit(endpoint).query:
            raise ValueError("Endpoint requires HTTPS without query parameters")
        validate_source_url(endpoint, allowed_hosts={host})
        item["repositories"] = sorted({str(r).lower() for r in item["repositories"]})
        result = register_extension(item)
    except (ExtensionRegistryError, SourcePolicyError, ValueError, TypeError) as exc:
        raise HTTPException(422,"Invalid MCP manifest") from exc
    return {"id":result["extension_id"],"version":result["version"],"execution":"blocked_unreviewed_transport","price_status":"unverified"}

@router.get("/api/mcp/servers")
async def discover_servers(repository: str, x_tenant_key: str | None = Header(default=None)):
    identity(x_tenant_key, repository, ("registry:read",))
    return {"repository":repository.lower(),"servers":servers(repository)}

class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    terms: list[str] = Field(default_factory=list,max_length=7)
    limit: int = Field(default=20,ge=1,le=50)

@router.post("/api/admin/mcp/discover")
async def discover_mcp(request: SearchRequest, x_admin_key: str | None = Header(default=None)):
    admin(x_admin_key)
    result = await discover_resources(DiscoverySearchRequest(kind="tool",terms=["MCP",*request.terms],limit=request.limit),x_admin_key=x_admin_key)
    return {**result,"note":"Open-source license or free label does not establish zero runtime cost. Review required."}

@router.get("/api/mcp/health")
async def gateway_health(repository: str, x_tenant_key: str | None = Header(default=None)):
    identity(x_tenant_key,repository,("registry:read",))
    return health(repository)

def health(repo):
    worker = worker_health()
    return {"gateway":"reachable","worker_configured":worker_ready(),
            "worker_status":worker.get("status","unknown"),
            "servers":servers(repo),"external_probes_enabled":False,
            "provider_cost_verified":False}

def obj(props=None, required=()):
    return {"type":"object","properties":props or {},"required":list(required),"additionalProperties":False}

def string(n=120):
    return {"type":"string","minLength":1,"maxLength":n}

def tool(name,description,scopes,schema,read=True):
    return {"name":name,"description":description,"inputSchema":schema,
            "annotations":{"readOnlyHint":read,"destructiveHint":False,"openWorldHint":False},
            "_scopes":scopes}

TOOLS = (
    tool("mcp_registry","List registered external MCP metadata; no remote calls",("registry:read",),obj()),
    tool("mcp_health","Read local gateway and worker health",("registry:read",),obj()),
    tool("agent_catalog","List tenant-visible central agents",("registry:read",),obj()),
    tool("agent_submit","Enqueue a fixed central agent; no paid fallback",("jobs:enqueue","inference:chat"),obj({"agent_id":string(),"idempotency_key":string(128),"payload":{"type":"object"}},("agent_id","idempotency_key","payload")),False),
    tool("agent_job_status","Read own encrypted job result",("jobs:read",),obj({"job_id":string(64)},("job_id",))),
    tool("event_publish","Publish an internal repository-scoped event for an explicitly deployed consumer",("events:publish",),obj({"event_type":string(),"consumer":string(),"idempotency_key":string(128),"payload":{"type":"object"}},("event_type","consumer","idempotency_key","payload")),False),
)

def visible(info):
    scopes=set(info["scopes"])
    return {t["name"]:t for t in TOOLS if set(t["_scopes"]).issubset(scopes)}

async def invoke(name,args,info,key,repo):
    t=visible(info).get(name)
    if not t:
        raise ValueError("Unknown or unauthorized tool")
    validate_instance(t["inputSchema"],args)
    if name=="mcp_registry": return {"servers":servers(repo)}
    if name=="mcp_health": return health(repo)
    if name=="agent_catalog":
        return {"agents":[a for a in list_agents(include_operator=False) if set(a["required_scopes"]).issubset(info["scopes"])]}
    if name=="agent_submit":
        payload={**args["payload"],"agent_id":args["agent_id"]}
        validate_agent_input(payload)
        return await submit_job(JobSubmitRequest(repository=repo,job_type="agent.execute",idempotency_key=args["idempotency_key"],payload=payload,max_attempts=3),x_tenant_key=key)
    if name=="agent_job_status":
        return await get_job_status(args["job_id"],repository=repo,x_tenant_key=key)
    if name=="event_publish":
        return await publish(PublishRequest(repository=repo,event_type=args["event_type"],schema_version=1,producer="koroush.mcp",consumer=args["consumer"],idempotency_key=args["idempotency_key"],payload=args["payload"]),x_tenant_key=key)
    raise ValueError("Unsupported tool")

def rpc_error(id_,code,message):
    return {"jsonrpc":"2.0","id":id_,"error":{"code":code,"message":message}}

def rpc_result(id_,result):
    return {"jsonrpc":"2.0","id":id_,"result":result}

@router.post("/mcp/{owner}/{repository}")
async def mcp_request(owner:str,repository:str,request:Request):
    # Reject browser origins by default. No permissive CORS or admin key fallback.
    origin=request.headers.get("origin")
    allowed={v.strip() for v in os.getenv("MCP_ALLOWED_ORIGINS","").split(",") if v.strip()}
    if origin is not None and origin not in allowed:
        raise HTTPException(403,"Origin not allowed")
    if os.getenv("MCP_GATEWAY_ENABLED","false").lower() not in {"true","1"}:
        raise HTTPException(503,"MCP gateway disabled")
    key=request.headers.get("x-tenant-key")
    auth=request.headers.get("authorization","")
    if auth.startswith("Bearer "):
        if key and key!=auth[7:]:
            raise HTTPException(401,"Conflicting authentication")
        key=auth[7:]
    repo=f"{owner}/{repository}".lower()
    info=identity(key,repo)
    if request.headers.get("content-type","").split(";")[0].strip().lower()!="application/json":
        raise HTTPException(415,"Expected application/json")
    protocol=request.headers.get("mcp-protocol-version")
    if protocol and protocol not in VERSIONS:
        raise HTTPException(400,"Unsupported MCP protocol version")
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>MAX_BODY:
            raise HTTPException(413,"MCP payload too large")
    try:
        msg=json.loads(body)
    except (ValueError,UnicodeError,RecursionError):
        return JSONResponse(rpc_error(None,-32700,"Parse error"))
    if not isinstance(msg,dict) or msg.get("jsonrpc")!="2.0" or not isinstance(msg.get("method"),str):
        return JSONResponse(rpc_error(None,-32600,"Invalid request"))
    id_=msg.get("id")
    if "id" in msg and (isinstance(id_,bool) or not isinstance(id_,(str,int))):
        return JSONResponse(rpc_error(None,-32600,"Invalid request id"))
    method=msg["method"]
    if "id" not in msg:
        # Notifications never trigger jobs or events.
        return Response(status_code=202)
    params=msg.get("params",{})
    if not isinstance(params,dict):
        return JSONResponse(rpc_error(id_,-32602,"Invalid params"))
    if method=="initialize":
        v=params.get("protocolVersion")
        result={"protocolVersion":v if v in VERSIONS else VERSIONS[-1],"capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"KOROUSH-CENTRAL-AI","version":"1.0.0"}}
    elif method=="ping": result={}
    elif method=="tools/list":
        result={"tools":[{k:v for k,v in t.items() if k!="_scopes"} for t in visible(info).values()]}
    elif method=="tools/call":
        try:
            value=await invoke(params.get("name"),params.get("arguments",{}),info,key,repo)
            text=json.dumps(value,ensure_ascii=False,allow_nan=False)
            if len(text.encode("utf-8"))>MAX_OUTPUT:
                raise ValueError("Tool output too large")
            result={"content":[{"type":"text","text":text}],"isError":False}
        except (ValueError,TypeError,SchemaValidationError,AgentContractError,ValidationError,HTTPException,RecursionError):
            result={"content":[{"type":"text","text":"Tool rejected, unavailable or unauthorized"}],"isError":True}
    else:
        return JSONResponse(rpc_error(id_,-32601,"Method not found"))
    return JSONResponse(rpc_result(id_,result))

@router.get("/mcp/{owner}/{repository}")
async def mcp_get(owner:str,repository:str):
    # Stateless JSON-only transport; no server-initiated SSE stream.
    return Response(status_code=405,headers={"Allow":"POST"})
