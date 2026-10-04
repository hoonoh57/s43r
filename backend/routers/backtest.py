import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.sim import simulate
from tools.data_loader import load_simulation_ticks

router = APIRouter(prefix="/api/backtest", tags=["Backtest"])

VARIANT_ENGINES = {
    "S4.3-R": "S4.3-R",
    "R2": "S4.3-R2",
    "R3": "S4.3-R3",
}


class BacktestCompareRequest(BaseModel):
    symbol: str
    target_date: str
    initial_cash: float = Field(default=10_000_000.0, gt=0, allow_inf_nan=False)
    variants: list[str] = Field(default_factory=lambda: list(VARIANT_ENGINES))
    fee_bps: float = Field(default=20.0, ge=0, allow_inf_nan=False)
    slippage_bps: float = Field(default=1.5, ge=0, allow_inf_nan=False)


def _run_variant_compare(req: BacktestCompareRequest) -> dict[str, Any]:
    target_date = req.target_date.strip()
    try:
        ticks = load_simulation_ticks(req.symbol, target_date)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not ticks:
        raise HTTPException(status_code=404, detail="해당 일자의 틱 데이터가 존재하지 않습니다.")
    if not req.variants:
        raise HTTPException(status_code=422, detail="비교할 전략 버전을 하나 이상 지정하세요.")
    if len(set(req.variants)) != len(req.variants):
        raise HTTPException(status_code=422, detail="전략 버전을 중복 지정할 수 없습니다.")
    unsupported = [variant for variant in req.variants if variant not in VARIANT_ENGINES]
    if unsupported:
        raise HTTPException(status_code=422, detail=f"지원하지 않는 전략 버전: {', '.join(unsupported)}")

    simulation_data = {
        "date": target_date,
        "ticks": [
            [
                tick["time"][:8],
                tick["time"][8:12],
                tick["price"],
                tick.get("volume", 1.0),
            ]
            for tick in ticks
        ],
    }
    results = {}
    for variant in req.variants:
        try:
            simulation = simulate(
                simulation_data,
                size=360,
                params={"strategy": VARIANT_ENGINES[variant]},
                slip=0,
                cost_pct=req.fee_bps / 50.0,
                capital=req.initial_cash,
                slippage_bps=req.slippage_bps,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{variant}: {exc}") from exc

        stats = simulation["stats"]
        net = float(stats["net"])
        entered = bool(stats["entered"])
        win_count = int(entered and net > 0)
        loss_count = int(entered and net < 0)
        equity_curve = [
            {"time": bar["t"], "value": round(req.initial_cash + value, 2)}
            for bar, value in zip(simulation["bars"], simulation["equity"])
            if bar["date"] == target_date
        ]
        metrics = {
            "total_trades": int(entered),
            "win_rate": 100.0 if win_count else 0.0,
            "total_return_pct": round(float(stats["ret"]), 2),
            "profit_factor": 999.0 if win_count else 0.0,
            "mdd_pct": round(abs(float(stats["mdd"])) / req.initial_cash * 100.0, 2),
            "win_count": win_count,
            "loss_count": loss_count,
            "avg_win": round(net if win_count else 0.0),
            "avg_loss": round(abs(net) if loss_count else 0.0),
            "final_equity": round(req.initial_cash + net),
        }
        results[variant] = {
            "variant": variant,
            "metrics": metrics,
            "equity_curve": equity_curve,
            "trades": simulation["fills"],
        }

    return {
        "status": "success",
        "symbol": req.symbol.strip(),
        "date": target_date,
        "data_source": "synthetic" if any(tick.get("synthetic") for tick in ticks) else "local",
        "results": results,
    }


@router.post("/run-compare")
async def run_compare_backtest(req: BacktestCompareRequest):
    return await asyncio.to_thread(_run_variant_compare, req)
