import pytest

from app.agent import editable_snapshot_paths, validate_fix_implementation, build_approval_digest
from app.config import settings


def test_implementation_accepts_only_existing_inspected_files():
    result = validate_fix_implementation(
        {"summary": "Update validation", "findings": ["Missing guard"],
         "files": [{"path": "app/main.py", "content": "print('safe')\n"}],
         "tests_to_run": ["pytest -q"]},
        {"app/main.py"},
    )
    assert result["files"][0]["path"] == "app/main.py"
    assert result["tests_to_run"] == ["pytest -q"]


@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd", "new.py", "app\\main.py"])
def test_implementation_rejects_unsafe_or_uninspected_paths(path):
    with pytest.raises(ValueError):
        validate_fix_implementation({"files": [{"path": path, "content": "x"}]}, {"app/main.py"})


def test_implementation_rejects_more_than_five_files():
    files = [{"path": f"f{i}.py", "content": "x"} for i in range(6)]
    with pytest.raises(ValueError):
        validate_fix_implementation({"files": files}, {f"f{i}.py" for i in range(6)})


def test_redacted_snapshot_files_are_never_editable():
    snapshot = {"files": [
        {"path": "app/safe.py", "content": "print(1)", "contains_redactions": False},
        {"path": "config.py", "content": "key=[REDACTED]", "contains_redactions": True},
        {"path": "legacy.py", "content": "print(2)"},
        {"path": "long.py", "content": "partial source", "content_truncated": True},
    ]}
    assert editable_snapshot_paths(snapshot) == {"app/safe.py", "legacy.py"}


def test_redacted_file_is_rejected_by_implementation_allowlist():
    allowed = editable_snapshot_paths({"files": [
        {"path": "config.py", "content": "key=[REDACTED]", "contains_redactions": True},
    ]})
    with pytest.raises(ValueError):
        validate_fix_implementation(
            {"files": [{"path": "config.py", "content": "key = \"[REDACTED]\""}]},
            allowed,
        )


def test_truncated_snapshot_files_are_never_editable():
    allowed = editable_snapshot_paths({"files": [
        {"path": "large_module.py", "content": "partial", "content_truncated": True},
    ]})
    assert allowed == set()


def test_approval_digest_binds_exact_preview_and_source_versions():
    implementation = {"summary": "Safe update", "findings": [],
        "files": [{"path": "app/main.py", "content": "print('approved')\\n"}],
        "tests_to_run": ["pytest -q"], "model": "test-model"}
    source_shas = {"app/main.py": "abc123"}
    digest = build_approval_digest("owner/repo", "fix validation", implementation, source_shas)
    assert digest == build_approval_digest("owner/repo", "fix validation", implementation, source_shas)
    changed = {**implementation, "files": [{"path": "app/main.py", "content": "print('changed')\\n"}]}
    assert digest != build_approval_digest("owner/repo", "fix validation", changed, source_shas)
    assert digest != build_approval_digest("owner/repo", "fix validation", implementation, {"app/main.py": "newsha"})
    assert digest != build_approval_digest("owner/repo", "different task", implementation, source_shas)

def test_approval_digest_is_signed_with_admin_secret(monkeypatch):
    implementation = {"summary": "Safe update", "findings": [],
        "files": [{"path": "app/main.py", "content": "approved"}],
        "tests_to_run": [], "model": "test-model"}
    source_shas = {"app/main.py": "abc123"}
    monkeypatch.setattr(settings, "admin_api_key", "first-admin-secret")
    first = build_approval_digest("owner/repo", "fix validation", implementation, source_shas)
    monkeypatch.setattr(settings, "admin_api_key", "second-admin-secret")
    second = build_approval_digest("owner/repo", "fix validation", implementation, source_shas)
    assert first != second
