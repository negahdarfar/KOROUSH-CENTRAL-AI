import pytest

from app.agent import validate_fix_implementation


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
