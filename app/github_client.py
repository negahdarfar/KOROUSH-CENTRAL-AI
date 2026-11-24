import httpx
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
