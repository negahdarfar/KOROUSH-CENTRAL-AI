from app.avalai_gateway import CAPABILITY_CATALOG, JSON_SURFACES


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
