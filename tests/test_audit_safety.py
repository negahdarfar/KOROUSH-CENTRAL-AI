from app.github_client import is_audit_candidate, redact_secrets


def test_audit_candidate_accepts_source_file():
    assert is_audit_candidate({"path": "app/main.py", "type": "blob", "size": 100})


def test_audit_candidate_rejects_env_and_secret_files():
    assert not is_audit_candidate({"path": ".env", "type": "blob", "size": 100})
    assert not is_audit_candidate({"path": "config/credentials.json", "type": "blob", "size": 100})
    assert not is_audit_candidate({"path": "keys/private_key.pem", "type": "blob", "size": 100})


def test_audit_candidate_rejects_generated_and_large_files():
    assert not is_audit_candidate({"path": "node_modules/pkg/index.js", "type": "blob", "size": 100})
    assert not is_audit_candidate({"path": "large.py", "type": "blob", "size": 1_000_001})
    assert not is_audit_candidate({"path": "image.png", "type": "blob", "size": 100})


def test_secret_redaction_masks_common_credentials():
    source = "api_key=abcdefghijk12345 ghp_abcdefghijklmnopqrstuvwxyz123456 AKIA1234567890ABCDEF"
    result = redact_secrets(source)
    assert "abcdefghijk12345" not in result
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in result
    assert "AKIA1234567890ABCDEF" not in result
    assert "[REDACTED" in result
