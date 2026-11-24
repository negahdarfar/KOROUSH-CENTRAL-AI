from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.quota_guard import QuotaExceeded, cancel_reservation, reserve_inference


def test_concurrent_requests_cannot_overbook_single_request_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "concurrent.sqlite3"))
    monkeypatch.setenv(
        "KOROUSH_REPO_QUOTAS",
        '{"org/repo":{"requests_per_day":1,"requests_per_month":1,'
        '"tokens_per_day":10000,"tokens_per_month":10000}}',
    )
    workers = 8
    barrier = Barrier(workers)

    def attempt(_):
        barrier.wait(timeout=5)
        try:
            return reserve_inference("org/repo", {"input": "small request"})
        except QuotaExceeded:
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(attempt, range(workers)))

    reservations = [item for item in results if item]
    assert len(reservations) == 1
    cancel_reservation(reservations[0])
