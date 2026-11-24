"""Safe runtime build metadata for deployment verification."""

import os


def runtime_version() -> dict:
    """Return non-secret build/deployment metadata supplied by the hosting platform."""
    commit_sha = os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("GIT_COMMIT_SHA") or None
    deployment_id = os.getenv("RAILWAY_DEPLOYMENT_ID") or None
    service_name = os.getenv("RAILWAY_SERVICE_NAME") or "KOROUSH CENTRAL AI"
    environment_name = os.getenv("RAILWAY_ENVIRONMENT_NAME") or None
    branch = os.getenv("RAILWAY_GIT_BRANCH") or None

    return {
        "service": service_name,
        "status": "identified" if commit_sha else "unknown",
        "commit_sha": commit_sha,
        "commit_short": commit_sha[:12] if commit_sha else None,
        "deployment_id": deployment_id,
        "environment": environment_name,
        "branch": branch,
        "source": "railway_environment" if commit_sha else "platform_metadata_unavailable",
    }
