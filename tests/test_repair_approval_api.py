import asyncio
import copy

import pytest
from fastapi import HTTPException

from app import main
from app.config import settings


def _snapshot(source_sha="blob-v1"):
    return {
        "default_branch": "main",
        "truncated": False,
        "file_count": 1,
        "files": [{
            "path": "app/example.py",
            "content": "print('old')\\n",
            "contains_redactions": False,
            "content_truncated": False,
            "source_sha": source_sha,
        }],
    }


def _implementation():
    return {
        "summary": "Update example",
        "findings": ["Example needs update"],
        "files": [{"path": "app/example.py", "content": "print('approved')\\n"}],
        "tests_to_run": ["pytest -q"],
        "model": "test-model",
    }


def test_preview_is_non_writing_and_exact_preview_can_be_published(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-secret")
    snapshot = _snapshot()
    published = {}

    async def get_snapshot(_repository):
        return copy.deepcopy(snapshot)

    async def generate(_repository, _task, _snapshot, model=None):
        return _implementation()

    async def publish(_repository, files, _summary, _tests, _base):
        published["files"] = copy.deepcopy(files)
        return {"branch": "ai-fix/test", "pull_request_number": 99, "merged": False}

    monkeypatch.setattr(main.gh, "get_repo_snapshot", get_snapshot)
    monkeypatch.setattr(main, "generate_fix_implementation", generate)
    monkeypatch.setattr(main, "publish_changes", publish)

    async def run():
        preview = await main.fix_preview(
            "owner", "repo", main.FixProposalRequest(task="fix the example safely"), "test-admin-secret"
        )
        assert preview["mode"] == "preview_only"
        assert preview["applied"] is False
        assert published == {}
        result = await main.fix_apply(
            "owner", "repo",
            main.FixApplyRequest(
                task="fix the example safely",
                confirm=True,
                approved_implementation=preview["implementation"],
                source_shas=preview["source_shas"],
                approval_digest=preview["approval_digest"],
            ),
            "test-admin-secret",
        )
        assert result["applied"] is True
        assert published["files"][0]["content"] == "print('approved')\\n"
        assert published["files"][0]["source_sha"] == "blob-v1"

    asyncio.run(run())


def test_apply_rejects_modified_preview_digest(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-secret")
    snapshot = _snapshot()
    called = {"publish": False}

    async def get_snapshot(_repository):
        return copy.deepcopy(snapshot)

    async def generate(_repository, _task, _snapshot, model=None):
        return _implementation()

    async def publish(*_args):
        called["publish"] = True
        return {}

    monkeypatch.setattr(main.gh, "get_repo_snapshot", get_snapshot)
    monkeypatch.setattr(main, "generate_fix_implementation", generate)
    monkeypatch.setattr(main, "publish_changes", publish)

    async def run():
        preview = await main.fix_preview(
            "owner", "repo", main.FixProposalRequest(task="fix the example safely"), "test-admin-secret"
        )
        modified = copy.deepcopy(preview["implementation"])
        modified["files"][0]["content"] = "print('unreviewed')\\n"
        with pytest.raises(HTTPException) as exc:
            await main.fix_apply(
                "owner", "repo",
                main.FixApplyRequest(task="fix the example safely", confirm=True,
                    approved_implementation=modified, source_shas=preview["source_shas"],
                    approval_digest=preview["approval_digest"]),
                "test-admin-secret",
            )
        assert exc.value.status_code == 422
        assert called["publish"] is False

    asyncio.run(run())


def test_apply_rejects_stale_source_sha(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-secret")
    state = {"source_sha": "blob-v1"}
    called = {"publish": False}

    async def get_snapshot(_repository):
        return _snapshot(state["source_sha"])

    async def generate(_repository, _task, _snapshot, model=None):
        return _implementation()

    async def publish(*_args):
        called["publish"] = True
        return {}

    monkeypatch.setattr(main.gh, "get_repo_snapshot", get_snapshot)
    monkeypatch.setattr(main, "generate_fix_implementation", generate)
    monkeypatch.setattr(main, "publish_changes", publish)

    async def run():
        preview = await main.fix_preview(
            "owner", "repo", main.FixProposalRequest(task="fix the example safely"), "test-admin-secret"
        )
        state["source_sha"] = "blob-v2"
        with pytest.raises(HTTPException) as exc:
            await main.fix_apply(
                "owner", "repo",
                main.FixApplyRequest(task="fix the example safely", confirm=True,
                    approved_implementation=preview["implementation"], source_shas=preview["source_shas"],
                    approval_digest=preview["approval_digest"]),
                "test-admin-secret",
            )
        assert exc.value.status_code == 422
        assert called["publish"] is False

    asyncio.run(run())
