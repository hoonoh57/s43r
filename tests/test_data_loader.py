import json

import pytest

from tools import data_loader
from backend.routers import backtest


def configure_data_dirs(monkeypatch, tmp_path):
    ticks_dir = tmp_path / "ticks"
    data_dir = tmp_path / "data"
    tools_dir = tmp_path / "tools"
    ticks_dir.mkdir()
    data_dir.mkdir()
    tools_dir.mkdir()
    monkeypatch.setattr(data_loader, "TICKS_DATA_DIR", ticks_dir)
    monkeypatch.setattr(data_loader, "DATA_DIR", data_dir)
    monkeypatch.setattr(data_loader, "TOOLS_DATA_DIR", tools_dir)
    return ticks_dir, data_dir, tools_dir


def test_loads_cybos_json_with_prior_day_warmup_ticks(monkeypatch, tmp_path):
    ticks_dir, _, _ = configure_data_dirs(monkeypatch, tmp_path)
    (ticks_dir / "005930_20261002.json").write_text(json.dumps({
        "source": "cybos",
        "ticks": [
            ["20261001", "1530", 9900, 20],
            ["20261002", "0900", 10000, 10],
            ["20261002", "0901", 10010, 15],
        ],
    }), encoding="utf-8")

    assert data_loader.load_simulation_ticks("005930", "20261002") == [
        {"time": "20261001153000", "price": 9900.0, "volume": 20.0},
        {"time": "20261002090000", "price": 10000.0, "volume": 10.0},
        {"time": "20261002090100", "price": 10010.0, "volume": 15.0},
    ]


def test_loads_csv_time_and_price_aliases(monkeypatch, tmp_path):
    _, data_dir, _ = configure_data_dirs(monkeypatch, tmp_path)
    (data_dir / "005930_20261002.csv").write_text(
        "체결시간,체결가\n2026-10-02 09:00:00,\"10,000\"\n2026-10-01 09:00:00,9900\n",
        encoding="utf-8-sig",
    )

    assert data_loader.load_simulation_ticks("005930", "20261002") == [
        {"time": "20261001090000", "price": 9900.0, "volume": 1.0},
        {"time": "20261002090000", "price": 10000.0, "volume": 1.0},
    ]


def test_loads_jsonl_and_sorts_ticks(monkeypatch, tmp_path):
    _, data_dir, _ = configure_data_dirs(monkeypatch, tmp_path)
    (data_dir / "005930_20261002.jsonl").write_text(
        '{"time":"20261002090200","price":10020}\n'
        '{"time":"20261002090100","price":10010}\n',
        encoding="utf-8",
    )

    assert data_loader.load_simulation_ticks("005930", "20261002") == [
        {"time": "20261002090100", "price": 10010.0, "volume": 1.0},
        {"time": "20261002090200", "price": 10020.0, "volume": 1.0},
    ]


def test_generates_full_session_mock_data_when_no_file_exists(monkeypatch, tmp_path):
    configure_data_dirs(monkeypatch, tmp_path)

    ticks = data_loader.load_simulation_ticks("005930", "20261004")

    assert len(ticks) == 79 * 360
    assert ticks[0]["time"] == "20261004090000"
    assert ticks[-1]["time"] == "20261004153000"
    assert all(tick["synthetic"] for tick in ticks)
    assert ticks == data_loader.load_simulation_ticks("005930", "20261004")


def test_invalid_date_is_rejected():
    with pytest.raises(ValueError, match="YYYYMMDD"):
        data_loader.load_simulation_ticks("005930", "20260230")
    with pytest.raises(ValueError, match="YYYYMMDD"):
        data_loader.load_simulation_ticks("005930", "2026104")


def test_invalid_existing_file_is_not_silently_replaced_by_mock_data(monkeypatch, tmp_path):
    _, data_dir, _ = configure_data_dirs(monkeypatch, tmp_path)
    (data_dir / "005930_20261002.csv").write_text(
        "unexpected,columns\nx,y\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="유효한 틱"):
        data_loader.load_simulation_ticks("005930", "20261002")


def test_compare_route_runs_all_registered_strategy_variants(monkeypatch):
    prices = (10000.0, 10100.0, 10200.0)
    ticks = [
        {"time": f"20261004{hour:02d}{minute:02d}00", "price": price, "volume": 100.0}
        for (hour, minute), price in zip(((9, 0), (9, 4), (9, 8)), prices)
        for _ in range(360)
    ]
    monkeypatch.setattr(backtest, "load_simulation_ticks", lambda symbol, day: ticks)

    result = backtest._run_variant_compare(
        backtest.BacktestCompareRequest(symbol="0015G0", target_date="20261004")
    )

    assert result["status"] == "success"
    assert set(result["results"]) == {"S4.3-R", "R2", "R3"}
    assert all(len(value["equity_curve"]) == 3 for value in result["results"].values())
    assert all("mdd_pct" in value["metrics"] for value in result["results"].values())
