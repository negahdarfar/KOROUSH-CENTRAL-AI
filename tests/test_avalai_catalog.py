from app.avalai import extract_model_catalog


def test_extract_model_catalog_keeps_only_valid_model_ids():
    payload = {
        "data": [
            {"id": "chat-model-a", "owned_by": "provider"},
            {"id": "image-model", "owned_by": "provider"},
            {"owned_by": "invalid"},
            "not-an-object",
            {"id": "", "owned_by": "invalid"},
        ]
    }

    assert extract_model_catalog(payload) == [
        {"id": "chat-model-a", "owned_by": "provider", "mode": None},
        {"id": "image-model", "owned_by": "provider", "mode": None},
    ]


def test_extract_model_catalog_handles_unexpected_payload():
    assert extract_model_catalog([]) == []
    assert extract_model_catalog({"data": None}) == []
