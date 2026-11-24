import httpx
from .config import settings

API = "https://api.github.com"

class GitHubClient:
    def _headers(self):
        if not settings.github_token:
            raise RuntimeError("GITHUB_TOKEN is not configured")
        return {"Authorization": f"Bearer {settings.github_token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    async def list_repositories(self):
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{API}/user/repos", headers=self._headers(), params={"per_page": 100, "sort": "updated"})
            r.raise_for_status()
            repos = r.json()
        allowed = settings.repo_allowlist
        if allowed:
            repos = [x for x in repos if x.get("full_name") in allowed]
        return [{"full_name": x.get("full_name"), "private": x.get("private"), "default_branch": x.get("default_branch"), "html_url": x.get("html_url")} for x in repos]

    async def get_repo_tree(self, full_name: str):
        if settings.repo_allowlist and full_name not in settings.repo_allowlist:
            raise PermissionError("Repository is not in ALLOWED_REPOS")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{API}/repos/{full_name}", headers=self._headers())
            r.raise_for_status()
            meta = r.json()
            branch = meta["default_branch"]
            t = await client.get(f"{API}/repos/{full_name}/git/trees/{branch}", headers=self._headers(), params={"recursive": "1"})
            t.raise_for_status()
            return {"default_branch": branch, "truncated": t.json().get("truncated", False), "tree": [{"path": x.get("path"), "type": x.get("type"), "size": x.get("size")} for x in t.json().get("tree", [])]}
