from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
import os

# variants.py에서 팩토리 또는 클래스 로드
from backend.variants import create_strategy_variant
from backend.backtest_engine import SingleVariantRunner
# tools/ 시뮬레이션 데이터 로더
from tools.data_loader import load_simulation_ticks  # 기존 틱 데이터 로딩 함수 연결

router = APIRouter(prefix="/api/backtest", tags=["Backtest"])

class BacktestCompareRequest(BaseModel):
    symbol: str
    target_date: str
    initial_cash: float = 10000000.0
    variants: List[str] = ["S4.3-R", "R2", "R3"]
    fee_bps: float = 20.0
    slippage_bps: float = 1.5

@router.post("/run-compare")
async def run_compare_backtest(req: BacktestCompareRequest):
    """
    동일한 틱 데이터 스트림을 S4.3-R, R2, R3 세 전략에 동시 주입하여 비교 결과를 반환
    """
    ticks = load_simulation_ticks(req.symbol, req.target_date)
    if not ticks:
        raise HTTPException(status_code=404, detail="해당 일자의 틱 데이터가 존재하지 않습니다.")

    runners = {}
    for v_name in req.variants:
        strat_instance = create_strategy_variant(v_name)
        runners[v_name] = SingleVariantRunner(
            variant_name=v_name,
            strategy_instance=strat_instance,
            initial_cash=req.initial_cash,
            fee_bps=req.fee_bps,
            slippage_bps=req.slippage_bps
        )

    # 틱 Replay 루프 (동시 주입)
    for tick in ticks:
        for runner in runners.values():
            runner.on_tick(tick)

    # 결과 수집
    results = {}
    for v_name, runner in runners.items():
        results[v_name] = runner.finalize()

    return {
        "status": "success",
        "symbol": req.symbol,
        "date": req.target_date,
        "results": results
    }