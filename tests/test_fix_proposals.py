import json
import pytest

from app.agent import validate_fix_proposal


def test_valid_proposal_is_marked_not_applied():
    raw = json.dumps({
        "summary": "Fix input validation",
        "findings": ["Missing boundary check"],
        "changes": [{"path": "app/main.py", "diff": "--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-old\n+new"}],
        "tests_to_run": ["pytest -q"],
    })
    result = validate_fix_proposal(raw, {"app/main.py"})
    assert result["status"] == "proposal_only_not_applied"
    assert len(result["changes"]) == 1


def test_proposal_rejects_paths_outside_snapshot():
    raw = json.dumps({"summary": "Bad path", "findings": [], "changes": [{"path": "../secrets.txt", "diff": "+bad"}], "tests_to_run": []})
    with pytest.raises(ValueError):
        validate_fix_proposal(raw, {"app/main.py"})


def test_proposal_rejects_unknown_existing_path():
    raw = json.dumps({"summary": "Unknown path", "findings": [], "changes": [{"path": "new_file.py", "diff": "+x"}], "tests_to_run": []})
    with pytest.raises(ValueError):
        validate_fix_proposal(raw, {"app/main.py"})


def test_proposal_rejects_more_than_five_files():
    changes = [{"path": f"f{i}.py", "diff": "+x"} for i in range(6)]
    raw = json.dumps({"summary": "Too many", "findings": [], "changes": changes, "tests_to_run": []})
    with pytest.raises(ValueError):
        validate_fix_proposal(raw, {f"f{i}.py" for i in range(6)})


def test_proposal_accepts_fenced_json():
    raw = '```json\n{"summary":"No change","findings":[],"changes":[],"tests_to_run":[]}\n```'
    result = validate_fix_proposal(raw, {"app/main.py"})
    assert result["changes"] == []