from fastapi.testclient import TestClient

from backend.app import create_app
from backend.routers import backtest


def test_backtest_skips_session_token_but_keeps_local_origin_checks(monkeypatch, tmp_path):
    ticks = [
        {"time": "20261004090000", "price": 10000.0, "volume": 1.0}
        for _ in range(360)
    ]
    monkeypatch.setattr(backtest, "load_simulation_ticks", lambda symbol, day: ticks)

    with TestClient(create_app(tmp_path)) as client:
        payload = {"symbol": "0015G0", "target_date": "20261004"}

        response = client.post("/api/backtest/run-compare", json=payload)
        assert response.status_code == 200
        assert set(response.json()["results"]) == {"S4.3-R", "R2", "R3"}
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"]

        denied = client.post("/api/backtest/run-compare", headers={"Origin": "https://evil.example"}, json=payload)
        assert denied.status_code == 403

        denied = client.post("/api/backtest/run-compare", headers={"Host": "evil.example"}, json=payload)
        assert denied.status_code == 403

        denied = client.post("/api/demo", json={})
        assert denied.status_code == 403
