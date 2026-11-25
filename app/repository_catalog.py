"""Bounded repository discovery and tenant-scoped capability matching.

Discovery is not authorization. No code installation or secret provisioning.
"""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from .quota_guard import _db_path
from .config import settings
from .agent_registry import list_agents
from .extension_registry import list_extensions
from .integration_profiles import list_integration_profiles

REPO_PATTERN=re.compile(r"[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?/[a-z0-9][a-z0-9._-]{0,99}")
PROFILES={"forex":"koroush.forex","youtube":"koroush.youtube","ptc":"koroush.ptc","nft":"koroush.nft"}
KNOWN={"daily-forex-analyze-":"forex","youtube-factory-":"youtube","ptc-earning-":"ptc","nft-art-factory":"nft"}

def normalize(repo):
    if not isinstance(repo,str) or not REPO_PATTERN.fullmatch(repo.lower()) or repo.lower().endswith(".git"):
        raise ValueError("Invalid repository identity")
    return repo.lower()

def match(repo):
    name=normalize(repo).split("/")[1]
    domain=KNOWN.get(name,"general")
    return {"domain":domain,"profile":PROFILES.get(domain),"match_status":"exact_name_hint" if domain!="general" else "generic_review"}

def connect():
    path=_db_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(str(path),timeout=10)
    conn.row_factory=sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS repository_catalog (
       repository TEXT PRIMARY KEY, domain TEXT NOT NULL, profile TEXT,
       observed_at TEXT NOT NULL, visibility TEXT NOT NULL, default_branch TEXT,
       archived INTEGER NOT NULL DEFAULT 0
    )""")
    return conn

def reconcile(items):
    now=datetime.now(timezone.utc).isoformat()
    approved={r.lower() for r in settings.repo_allowlist}
    rows=[]
    with connect() as conn:
        for item in items:
            try: repo=normalize(item["full_name"])
            except (ValueError,KeyError,TypeError): continue
            if not isinstance(item.get("private"),bool): continue
            domain=match(repo)
            visibility="private" if item["private"] else "public"
            branch=item.get("default_branch")
            if not isinstance(branch,str) or len(branch)>200: branch=None
            conn.execute("""INSERT INTO repository_catalog(repository,domain,profile,observed_at,visibility,default_branch)
              VALUES(?,?,?,?,?,?) ON CONFLICT(repository) DO UPDATE SET
              domain=excluded.domain,profile=excluded.profile,observed_at=excluded.observed_at,
              visibility=excluded.visibility,default_branch=excluded.default_branch""",
              (repo,domain["domain"],domain["profile"],now,visibility,branch))
            rows.append({"repository":repo,**domain,"operator_approved":repo in approved,"state":"discovered_only"})
    return rows

def catalog():
    approved={r.lower() for r in settings.repo_allowlist}
    with connect() as conn:
        rows=conn.execute("SELECT repository,domain,profile,observed_at,visibility,default_branch FROM repository_catalog ORDER BY repository").fetchall()
    return [{**dict(row),"operator_approved":row["repository"] in approved,"state":"discovered_only"} for row in rows]

def capability_snapshot(repo,scopes):
    repo=normalize(repo)
    hint=match(repo)
    profile=next((p for p in list_integration_profiles() if p["id"]==hint["profile"]),None)
    agents=[a for a in list_agents(include_operator=False) if set(a["required_scopes"]).issubset(scopes)]
    if profile:
        allowed=set(profile["shared_agents"])
        agents=[a for a in agents if a["id"] in allowed]
    extensions=list_extensions(repository=repo) if "registry:read" in scopes else []
    data={"contract_version":1,"repository":repo,"profile":hint,"agents":agents,"extensions":extensions,
          "policy":{"zero_cost":True,"auto_install":False,"auto_grant":False,"external_execution":False}}
    data["revision"]=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    return data
