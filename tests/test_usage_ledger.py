from app.usage_ledger import normalize_usage, record_usage, usage_summary


def test_normalize_openai_and_responses_usage_shapes():
    assert normalize_usage({"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10}) == (4, 6, 10)
    assert normalize_usage({"input_tokens": 3, "output_tokens": 5}) == (3, 5, 8)
    assert normalize_usage(None) == (0, 0, 0)


def test_repository_usage_isolated_and_provider_request_id_is_idempotent(tmp_path, monkeypatch):
    db = tmp_path / "usage.sqlite3"
    monkeypatch.setenv("USAGE_DB_PATH", str(db))
    assert record_usage(repository="Org/Alpha", provider="avalai", model="free-model",
                        surface="chat_completions", usage={"prompt_tokens": 7, "completion_tokens": 2},
                        provider_request_id="req-1")
    assert not record_usage(repository="org/alpha", provider="avalai", model="free-model",
                            surface="chat_completions", usage={"total_tokens": 99},
                            provider_request_id="req-1")
    assert record_usage(repository="org/beta", provider="avalai", model="free-model",
                        surface="responses", usage={"input_tokens": 1, "output_tokens": 4},
                        provider_request_id="req-2")
    summary = usage_summary()
    alpha = next(row for row in summary["repositories"] if row["repository"] == "org/alpha")
    beta = next(row for row in summary["repositories"] if row["repository"] == "org/beta")
    assert alpha["requests"] == 1 and alpha["total_tokens"] == 9
    assert beta["requests"] == 1 and beta["total_tokens"] == 5
    assert alpha["estimated_cost_usd"] == 0
