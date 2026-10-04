import math
from typing import List, Dict, Any

class BacktestMetrics:
    @staticmethod
    def calculate(initial_cash: float, trades: List[Dict[str, Any]], equity_curve: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_return_pct": 0.0,
                "profit_factor": 0.0,
                "mdd_pct": 0.0,
                "win_count": 0,
                "loss_count": 0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "final_equity": initial_cash
            }

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] < 0]

        total_trades = len(trades)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades) * 100.0 if total_trades > 0 else 0.0

        total_profit = sum(t["pnl"] for t in wins)
        total_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else (999.0 if total_profit > 0 else 0.0)

        final_equity = equity_curve[-1]["value"] if equity_curve else initial_cash
        total_return_pct = ((final_equity - initial_cash) / initial_cash) * 100.0

        # MDD 계산
        peak = initial_cash
        max_drawdown = 0.0
        for pt in equity_curve:
            val = pt["value"]
            if val > peak:
                peak = val
            drawdown = (peak - val) / peak if peak > 0 else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        avg_win = (total_profit / win_count) if win_count > 0 else 0.0
        avg_loss = (total_loss / loss_count) if loss_count > 0 else 0.0

        return {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "total_return_pct": round(total_return_pct, 2),
            "profit_factor": round(profit_factor, 2),
            "mdd_pct": round(max_drawdown * 100.0, 2),
            "win_count": win_count,
            "loss_count": loss_count,
            "avg_win": round(avg_win, 0),
            "avg_loss": round(avg_loss, 0),
            "final_equity": round(final_equity, 0)
        }


class SingleVariantRunner:
    """
    단일 전략 변형(Variant)에 대해 체결/포지션/자산곡선을 시뮬레이션하는 러너
    """
    def __init__(self, variant_name: str, strategy_instance, initial_cash: float = 10000000.0, fee_bps: float = 20.0, slippage_bps: float = 1.5):
        self.variant_name = variant_name
        self.strategy = strategy_instance
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.fee_rate = fee_bps / 10000.0
        self.slippage_rate = slippage_bps / 10000.0
        
        self.position_qty = 0
        self.avg_price = 0.0
        self.trades = []
        self.equity_curve = []
        self.current_entry_time = None

    def on_tick(self, tick: Dict[str, Any]):
        time_str = tick.get("time")
        price = float(tick["price"])
        
        # 전략 신호 추출 (variants.py 인터페이스 호출)
        signal = self.strategy.on_tick(tick)
        
        # 1. 매수 체결 처리 (BUY)
        if signal == "BUY" and self.position_qty == 0:
            exec_price = price * (1.0 + self.slippage_rate)
            # 최대 매수 가능 수량 계산 (전액 또는 지정 비율)
            alloc_cash = self.cash * 0.95
            qty = int(alloc_cash // exec_price)
            if qty > 0:
                cost = qty * exec_price
                fee = cost * self.fee_rate
                self.cash -= (cost + fee)
                self.position_qty = qty
                self.avg_price = exec_price
                self.current_entry_time = time_str

        # 2. 매도/청산 체결 처리 (SELL / TP / SL)
        elif signal in ["SELL", "TP", "SL", "CLOSE"] and self.position_qty > 0:
            exec_price = price * (1.0 - self.slippage_rate)
            revenue = self.position_qty * exec_price
            fee = revenue * self.fee_rate
            net_revenue = revenue - fee
            
            buy_cost = self.position_qty * self.avg_price
            pnl = net_revenue - buy_cost
            ret_pct = (pnl / buy_cost) * 100.0 if buy_cost > 0 else 0.0

            self.cash += net_revenue
            self.trades.append({
                "entry_time": self.current_entry_time,
                "exit_time": time_str,
                "qty": self.position_qty,
                "buy_price": round(self.avg_price, 1),
                "sell_price": round(exec_price, 1),
                "pnl": round(pnl, 0),
                "return_pct": round(ret_pct, 2),
                "reason": signal
            })
            self.position_qty = 0
            self.avg_price = 0.0
            self.current_entry_time = None

        # 현재 평가 자산 기록 (차트 시각화용)
        current_equity = self.cash + (self.position_qty * price)
        self.equity_curve.append({
            "time": time_str,
            "value": round(current_equity, 0)
        })

    def finalize(self) -> Dict[str, Any]:
        metrics = BacktestMetrics.calculate(self.initial_cash, self.trades, self.equity_curve)
        return {
            "variant": self.variant_name,
            "metrics": metrics,
            "equity_curve": self.equity_curve,
            "trades": self.trades
        }