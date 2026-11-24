import httpx

import re


BLOCKED_AUDIT_PARTS = (
    ".git/", "node_modules/", ".venv/", "__pycache__/", "dist/", "build/",
    ".terraform/", "vendor/", "coverage/"
)
SAFE_AUDIT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml",
    ".yml", ".md", ".txt", ".html", ".css", ".sh", ".sql", ".pine"
}
BLOCKED_AUDIT_NAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials.json", "secrets.json"
}


def is_audit_candidate(item: dict) -> bool:
    path = item.get("path", "")
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    suffix = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if item.get("type") != "blob" or not path or name in BLOCKED_AUDIT_NAMES:
        return False
    if any(part in lower for part in BLOCKED_AUDIT_PARTS):
        return False
    if name.startswith(".env") or any(term in name for term in ("secret", "credential", "token", "private_key")):
        return False
    if suffix not in SAFE_AUDIT_SUFFIXES and name not in {"dockerfile", "makefile"}:
        return False
    size = item.get("size")
    if size is not None and size > 1_000_000:
        return False
    return True


def redact_secrets(content: str) -> str:
    patterns = [
        (r"(?i)(api[_-]?key|secret|password|access[_-]?token)\s*[:=]\s*['\"]?[^\s'\"]{8,}", r"\1=[REDACTED]"),
        (r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b", "[REDACTED_GITHUB_TOKEN]"),
        (r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", "[REDACTED_GITHUB_TOKEN]"),
        (r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED_AWS_KEY]"),
        (r"\bsk-[A-Za-z0-9_-]{20,}\b", "[REDACTED_API_KEY]"),
    ]
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)
    return content

from .config import settings

API = "https://api.github.com"


class GitHubClient:
    def _headers(self):
        if not settings.github_token:
            raise RuntimeError("GITHUB_TOKEN is not configured")
        return {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def list_repositories(self):
        """Return every repository visible to the authenticated GitHub account."""
        repos = []
        async with httpx.AsyncClient(timeout=30) as client:
            page = 1
            while True:
                response = await client.get(
                    f"{API}/user/repos",
                    headers=self._headers(),
                    params={
                        "per_page": 100,
                        "page": page,
                        "sort": "updated",
                        "visibility": "all",
                        "affiliation": "owner,collaborator,organization_member",
                    },
                )
                response.raise_for_status()
                batch = response.json()
                repos.extend(batch)
                if len(batch) < 100:
                    break
                page += 1

        return [
            {
                "full_name": item.get("full_name"),
                "private": item.get("private"),
                "default_branch": item.get("default_branch"),
                "html_url": item.get("html_url"),
            }
            for item in repos
        ]

    async def get_repo_tree(self, full_name: str):
        # Enforce the optional explicit allowlist before making any GitHub API calls.
        allowlist = settings.repo_allowlist
        if allowlist and full_name not in allowlist:
            raise PermissionError(
                "Repository is not in ALLOWED_REPOS; add its exact owner/name to the service configuration"
            )

        # Only inspect repositories actually visible to this GitHub token.
        accessible = {item["full_name"] for item in await self.list_repositories()}
        if full_name not in accessible:
            raise PermissionError(
                "Repository is not visible to GITHUB_TOKEN; check GitHub App installation and token permissions"
            )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{API}/repos/{full_name}", headers=self._headers()
            )
            response.raise_for_status()
            metadata = response.json()
            branch = metadata["default_branch"]
            tree_response = await client.get(
                f"{API}/repos/{full_name}/git/trees/{branch}",
                headers=self._headers(),
                params={"recursive": "1"},
            )
            tree_response.raise_for_status()
            tree_data = tree_response.json()
            return {
                "default_branch": branch,
                "truncated": tree_data.get("truncated", False),
                "tree": [
                    {
                        "path": item.get("path"),
                        "type": item.get("type"),
                        "size": item.get("size"),
                    }
                    for item in tree_data.get("tree", [])
                ],
            }

    async def get_repo_snapshot(self, full_name: str, max_files: int = 20, max_chars_per_file: int = 12000):
        """Return a bounded source snapshot while excluding likely secrets and binary files."""
        import base64

        inventory = await self.get_repo_tree(full_name)
        selected = [item["path"] for item in inventory["tree"] if is_audit_candidate(item)]

        files = []
        total_chars = 0
        async with httpx.AsyncClient(timeout=30) as client:
            for path in selected[:max_files]:
                response = await client.get(
                    f"{API}/repos/{full_name}/contents/{path}",
                    headers=self._headers(),
                    params={"ref": inventory["default_branch"]},
                )
                if response.status_code != 200:
                    continue
                payload = response.json()
                if payload.get("encoding") != "base64" or not payload.get("content"):
                    continue
                try:
                    content = base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
                except Exception:
                    continue
                content_truncated = len(content) > max_chars_per_file
                original_content = content[:max_chars_per_file]
                sanitized_content = redact_secrets(original_content)
                contains_redactions = sanitized_content != original_content
                if total_chars + len(sanitized_content) > 100000:
                    break
                files.append({
                    "path": path,
                    "content": sanitized_content,
                    "contains_redactions": contains_redactions,
                    "content_truncated": content_truncated,
                    "source_sha": payload.get("sha"),
                })
                total_chars += len(sanitized_content)

        return {
            "default_branch": inventory["default_branch"],
            "truncated": inventory["truncated"],
            "file_count": len(files),
            "files": files,
        }
