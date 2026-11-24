"""Safe GitHub branch + pull-request publisher for explicitly approved AI changes."""
import re
import httpx

from .config import settings

API = "https://api.github.com"


def _headers():
    if not settings.github_token:
        raise RuntimeError("GITHUB_TOKEN is not configured")
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def publish_changes(repository: str, files: list[dict], summary: str, tests: list[str], base_branch: str) -> dict:
    """Create a new branch, commit approved existing-file replacements, then open a PR."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository name")
    if settings.repo_allowlist and repository not in settings.repo_allowlist:
        raise PermissionError("Repository is not in ALLOWED_REPOS")
    if not files or len(files) > 5:
        raise ValueError("Only one to five approved file replacements can be published")
    async with httpx.AsyncClient(timeout=45) as client:
        headers = _headers()
        repos = await client.get(f"{API}/user/repos", headers=headers, params={"per_page": 100, "visibility": "all", "affiliation": "owner,collaborator,organization_member"})
        repos.raise_for_status()
        if repository not in {r.get("full_name") for r in repos.json()}:
            raise PermissionError("Repository is not accessible to GITHUB_TOKEN")
        meta = await client.get(f"{API}/repos/{repository}", headers=headers)
        meta.raise_for_status()
        default_branch = meta.json()["default_branch"]
        if base_branch != default_branch:
            raise ValueError("For safety, AI repair pull requests must target the repository default branch")
        base = await client.get(f"{API}/repos/{repository}/git/ref/heads/{base_branch}", headers=headers)
        base.raise_for_status()
        base_sha = base.json()["object"]["sha"]
        stamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%d%H%M%S")
        branch = f"ai-fix/{stamp}"
        created = await client.post(f"{API}/repos/{repository}/git/refs", headers=headers, json={"ref": f"refs/heads/{branch}", "sha": base_sha})
        created.raise_for_status()
        commits = []
        for item in files:
            path, content = item["path"], item["content"]
            if path.startswith("/") or ".." in path.split("/") or "\\" in path:
                raise ValueError("Unsafe file path")
            current = await client.get(f"{API}/repos/{repository}/contents/{path}", headers=headers, params={"ref": base_branch})
            current.raise_for_status()
            current_data = current.json()
            if current_data.get("type") != "file" or not current_data.get("sha"):
                raise ValueError(f"Target is not an existing file: {path}")
            update = await client.put(
                f"{API}/repos/{repository}/contents/{path}",
                headers=headers,
                json={
                    "message": f"AI repair: update {path}",
                    "content": __import__("base64").b64encode(content.encode("utf-8")).decode("ascii"),
                    "sha": current_data["sha"],
                    "branch": branch,
                },
            )
            update.raise_for_status()
            commits.append(update.json().get("commit", {}).get("sha"))
        body = (
            "## AI-proposed changes\n\n" + summary[:2000] +
            "\n\n## Files changed\n" + "\n".join(f"- `{x['path']}`" for x in files) +
            "\n\n## Suggested tests (not run by this service)\n" +
            ("\n".join(f"- `{x}`" for x in tests[:10]) or "- No tests specified") +
            "\n\n## Safety\n- Changes are isolated on a new branch.\n- This pull request is not merged automatically.\n- Review the diff and CI results before merging."
        )
        pr = await client.post(
            f"{API}/repos/{repository}/pulls",
            headers=headers,
            json={"title": "AI-assisted repair: " + (summary[:120] or "proposed changes"), "head": branch, "base": base_branch, "body": body, "draft": True},
        )
        pr.raise_for_status()
        data = pr.json()
        return {"branch": branch, "pull_request_number": data["number"], "pull_request_url": data["html_url"], "base_branch": base_branch, "commit_shas": commits, "files_changed": [x["path"] for x in files], "merged": False}
