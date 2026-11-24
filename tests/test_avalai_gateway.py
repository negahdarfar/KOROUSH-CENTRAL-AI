import asyncio

import pytest

from app.avalai_gateway import CAPABILITY_CATALOG, JSON_SURFACES, ZERO_BUDGET_SAFE_SURFACES, require_approved_repository


def test_json_gateway_exposes_documented_capability_families():
    expected = {
        "responses", "chat_completions", "decisions", "systemone",
        "extraction", "embeddings", "images_generations", "audio_speech",
        "moderations", "rerank", "ocr", "videos",
    }
    assert expected == set(JSON_SURFACES)


def test_gateway_does_not_treat_upload_or_realtime_as_json():
    names = {item["name"]: item for item in CAPABILITY_CATALOG}
    assert names["audio_transcriptions"]["transport"] == "multipart_upload"
    assert names["images_edits"]["transport"] == "multipart_upload"
    assert names["realtime_audio"]["transport"] == "realtime"
    assert "audio_transcriptions" not in JSON_SURFACES


def test_all_gateway_paths_are_relative_fixed_routes():
    for item in JSON_SURFACES.values():
        assert item["path"].startswith("/")
        assert "://" not in item["path"]
        assert ".." not in item["path"]



def test_zero_budget_gateway_only_enables_chat_completions_until_surface_pricing_is_verified():
    assert ZERO_BUDGET_SAFE_SURFACES == frozenset({"chat_completions"})


def test_gateway_requires_explicit_approved_repository_identity():
    assert require_approved_repository("Org/Repo", {"org/repo"}) == "org/repo"
    with pytest.raises(RuntimeError, match="ALLOWED_REPOS"):
        require_approved_repository("org/repo", set())
    with pytest.raises(ValueError, match="not explicitly approved"):
        require_approved_repository("other/repo", {"org/repo"})
    with pytest.raises(ValueError, match="owner/repository"):
        require_approved_repository("org/../repo", {"org/../repo"})



@pytest.mark.parametrize(
    "surface",
    ["responses", "decisions", "systemone", "extraction", "embeddings",
     "images_generations", "audio_speech", "moderations", "rerank", "ocr", "videos"],
)
def test_non_chat_gateway_surfaces_fail_closed_before_provider_access(surface):
    from app.avalai_gateway import execute_avalai_surface

    with pytest.raises(ValueError, match="USD 0.00 policy"):
        asyncio.run(execute_avalai_surface(surface, {"model": "must-not-run"}, "org/repo"))
