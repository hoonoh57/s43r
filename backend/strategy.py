"""S4.3R reference-compatible, closed-bar strategy engine (no broker or orders).

Batch evaluation and streaming both use S43REngine.step. Prices in events are
backtest signal prices; fractions are relative to the ORIGINAL position.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Mapping

SOURCE_SHA256 = 'ade2280a11378e90a9fa7fb15a8ba7947d9259029df91009492d2ae82ddad368'


@dataclass(frozen=True)
class StrategyConfig:
    target_date: str
    capture_time: str = '0903'
    entry_start: str = '0904'
    entry_cutoff: str = '0930'
    exit_soft: str = '1003'
    exit_hard: str = '1030'
    base_rate_pct: float = 5.5
    apply_mfe_gate: bool = True
    macd_threshold: float = 0.15
    early_enabled: bool = True
    early_until: str = '0912'
    early_cum_eok: float = 15.0
    early_macd: float = 0.20
    apply_cum_gate: bool = True
    min_cum_eok: float = 3.0
    hard_stop_pct: float = -3.0
    tp1_pct: float = 2.5
    tp2_pct: float = 5.0
    tp_fraction: float = 0.30
    bep_pct: float = 0.2
    atr_trail_mult: float = 2.5
    vwap_runner_cut: float = 0.995
    vwap_extend: float = 1.01
    utc_offset_minutes: int = 540

    def __post_init__(self):
        datetime.strptime(self.target_date, '%Y%m%d')
        for value in (self.capture_time, self.entry_start, self.entry_cutoff,
                      self.exit_soft, self.exit_hard, self.early_until):
            if len(value) != 4:
                raise ValueError('times must be HHMM')
            datetime.strptime(value, '%H%M')
        if not self.capture_time < self.entry_start <= self.entry_cutoff <= self.exit_soft <= self.exit_hard:
            raise ValueError('invalid capture/entry/exit time order')
        for name in ('base_rate_pct', 'macd_threshold', 'early_cum_eok', 'early_macd',
                     'min_cum_eok', 'hard_stop_pct', 'tp1_pct', 'tp2_pct', 'tp_fraction',
                     'bep_pct', 'atr_trail_mult', 'vwap_runner_cut', 'vwap_extend'):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f'{name} must be finite')
        if not 0 < self.tp_fraction < .5:
            raise ValueError('two partial exits must leave a positive runner')


class Indicators:
    """Incremental equivalents of the five frozen app.js indicator functions."""
    def __init__(self, target_date):
        self.target_date = target_date
        self.n = 0
        self.volume = self.pv = self.amount = self.tr_sum = 0.0
        self.prev_close = None
        self.e0 = self.e1 = self.e2 = self.jma = 0.0
        self.ef = self.es = self.sig = 0.0
        self.atr = self.up = self.down = 0.0
        self.trend = 1
        self.beta = .45 * 6 / (.45 * 6 + 2)
        self.alpha = self.beta ** 2

    def step(self, b):
        c, h, lo, vol = (float(b[k]) for k in ('close', 'high', 'low', 'volume'))
        self.pv += ((h + lo + c) / 3.0) * vol
        self.volume += vol
        vwap = self.pv / self.volume if self.volume > 0 else c
        if b['date'] == self.target_date:
            self.amount += float(b.get('amount') or c * vol)
        else:
            self.amount = 0.0
        if not self.n:
            self.e0 = self.jma = self.ef = self.es = c
        else:
            a, beta = self.alpha, self.beta
            self.e0 = (1 - a) * c + a * self.e0
            self.e1 = (c - self.e0) * (1 - beta) + beta * self.e1
            self.e2 = (self.e0 + 1.5 * self.e1 - self.jma) * (1 - a) ** 2 + a ** 2 * self.e2
            self.jma += self.e2
            self.ef += (2.0 / 6) * (c - self.ef)
            self.es += (2.0 / 14) * (c - self.es)
            self.sig += (2.0 / 5) * ((self.ef - self.es) - self.sig)
        macd = ((self.ef - self.es) - self.sig) / c * 100.0 if c > 0 else 0.0
        tr = h - lo if not self.n else max(h - lo, abs(h - self.prev_close), abs(lo - self.prev_close))
        if self.n < 14:
            self.tr_sum += tr
        if self.n < 13:
            self.atr = tr
        elif self.n == 13:
            self.atr = self.tr_sum / 14
        else:
            self.atr = (self.atr * 13 + tr) / 14
        basic_up, basic_down = (h + lo) / 2.0 - 2 * self.atr, (h + lo) / 2.0 + 2 * self.atr
        if not self.n:
            self.up, self.down = basic_up, basic_down
        else:
            self.up = max(basic_up, self.up) if self.trend == 1 else basic_up
            self.down = min(basic_down, self.down) if self.trend == -1 else basic_down
            if self.trend == 1 and c < self.up:
                self.trend = -1
            elif self.trend == -1 and c > self.down:
                self.trend = 1
        self.prev_close = c
        self.n += 1
        return dict(vwap=vwap, jma=self.jma, trend=self.trend, atr=self.atr,
                    macd=macd, cum=self.amount / 1e8)


class S43REngine:
    """One symbol and target day. Feed seed bars, then CLOSED bars in source order.

    official_mfe=None is the real-time S4.3R mode. Decisions are intents only;
    this class never accesses credentials, accounts, network, or order APIs.
    """
    def __init__(self, config: StrategyConfig, official_mfe=None):
        self.config = config
        self.indicators = Indicators(config.target_date)
        self.block_reason = (f'MFE미달({official_mfe:.1f}%)'
                             if config.apply_mfe_gate and official_mfe is not None
                             and official_mfe < config.base_rate_pct else None)
        self.index = -1
        self.last_timestamp = 0
        self.capture_price = self.base_price = 0.0
        self.entry_start_idx = -1
        self.entered = self.closed = False
        self.entry_price = self.runner_high = 0.0
        self.entry_timestamp = self.exit_timestamp = None
        self.entry_time = '-'
        self.reason = '미체결'
        self.pnl = 0.0
        self.p1 = self.p2 = None
        self.prev_jma = self.prev_prev_jma = math.nan
        self.events = []
        self.values = []

    def _event(self, kind, b, fraction, reason):
        e = dict(kind=kind, time=b['timestamp'], price=float(b['close']),
                 fraction=fraction, reason=reason)
        self.events.append(e)
        return e

    def _exit(self, b, reason):
        ep, fraction = self.entry_price, self.config.tp_fraction
        part, rem = 0.0, 1.0
        if self.p1 is not None:
            part += (self.p1 - ep) / ep * (fraction * 100)
            rem -= fraction
        if self.p2 is not None:
            part += (self.p2 - ep) / ep * (fraction * 100)
            rem -= fraction
        self.pnl = part + (float(b['close']) - ep) / ep * (rem * 100)
        self.reason = reason
        self.closed = True
        self.exit_timestamp = b['timestamp']
        self._event('exit', b, rem, reason)

    def step(self, candle: Mapping):
        """Consume one completed candle; return only new entry/partial/exit intents."""
        b = dict(candle)
        for k in ('open', 'high', 'low', 'close', 'volume'):
            if not math.isfinite(float(b[k])):
                raise ValueError(f'non-finite candle {k}')
        date, time = str(b['date']), str(b['time'])
        tz = timezone(timedelta(minutes=self.config.utc_offset_minutes))
        raw_ts = int(datetime.strptime(date + time, '%Y%m%d%H%M').replace(tzinfo=tz).timestamp())
        b.update(date=date, time=time, timestamp=max(raw_ts, self.last_timestamp + 1))
        self.last_timestamp = b['timestamp']
        self.index += 1
        if self.block_reason:
            return []
        v = self.indicators.step(b)
        self.values.append(v)
        prev, prev2 = self.prev_jma, self.prev_prev_jma
        if self.index < 2:
            prev2 = prev
        self.prev_prev_jma, self.prev_jma = prev, v['jma']
        cfg, c = self.config, float(b['close'])
        if date == cfg.target_date:
            if time <= cfg.capture_time:
                self.capture_price = c
            if time >= cfg.entry_start and self.entry_start_idx < 0:
                self.entry_start_idx = self.index
                if self.capture_price <= 0:
                    self.capture_price = float(b['open'])
                if self.capture_price > 0:
                    self.base_price = self.capture_price * (1.0 + cfg.base_rate_pct / 100.0)
        if self.closed or self.entry_start_idx < 0 or self.capture_price <= 0:
            return []
        n = len(self.events)
        in_window = date == cfg.target_date and cfg.entry_start <= time <= cfg.entry_cutoff
        if not self.entered and in_window:
            setup = v['trend'] == 1 and v['macd'] >= cfg.macd_threshold and v['jma'] > prev
            pct = (c - self.capture_price) / self.capture_price * 100.0
            normal = setup and (not cfg.apply_mfe_gate or (c >= self.base_price and pct >= cfg.base_rate_pct))
            early = (cfg.early_enabled and setup and time <= cfg.early_until
                     and v['cum'] >= cfg.early_cum_eok and v['macd'] >= cfg.early_macd)
            if (normal or early) and (not cfg.apply_cum_gate or v['cum'] >= cfg.min_cum_eok):
                self.entered = True
                self.entry_price, self.entry_timestamp = c, b['timestamp']
                self.entry_time = time[:2] + ':' + time[2:]
                self.runner_high = float(b['high'])
                self._event('entry', b, 1.0, 'S4.3진입')
        if self.entered and b['timestamp'] > self.entry_timestamp:
            self.runner_high = max(self.runner_high, float(b['high']))
            pnl = (c - self.entry_price) / self.entry_price * 100.0
            turn_down = v['jma'] < prev and prev >= prev2
            if pnl <= cfg.hard_stop_pct:
                self._exit(b, f'초기손절(스탑{cfg.hard_stop_pct:.1f}%)')
            elif self.p1 is not None and pnl <= cfg.bep_pct:
                self._exit(b, '본전보호(BEP컷)')
            else:
                if self.p1 is None and pnl >= cfg.tp1_pct and turn_down:
                    self.p1 = c
                    self._event('partial', b, cfg.tp_fraction, '1차30%익절')
                if self.p1 is not None and self.p2 is None and pnl >= cfg.tp2_pct and turn_down:
                    self.p2 = c
                    self._event('partial', b, cfg.tp_fraction, '2차30%익절')
                atr = v['atr'] or (float(b['high']) - float(b['low']))
                if self.p2 is not None and c < self.runner_high - cfg.atr_trail_mult * atr:
                    self._exit(b, 'ATR동적트레일링컷')
                elif v['trend'] == -1 or (self.p1 is not None and c < v['vwap'] * cfg.vwap_runner_cut):
                    self._exit(b, '추세이탈(런너청산)' if self.p1 is not None or self.p2 is not None else 'ST하락(손절)')
                elif date == cfg.target_date and time > cfg.exit_soft:
                    strong = v['trend'] == 1 and c >= v['vwap'] * cfg.vwap_extend
                    if not strong or time >= cfg.exit_hard:
                        self._exit(b, '추세연장마감(10:30)' if time >= cfg.exit_hard else '10:03시간종료')
        return [dict(e) for e in self.events[n:]]

    def result(self):
        reason = (self.block_reason or ('데이터없음' if self.index < 0 else
                  '09:04봉없음' if self.entry_start_idx < 0 or self.capture_price <= 0 else
                  self.reason if self.entered else '미진입'))
        missing = reason == '09:04봉없음'
        return dict(entered=self.entered, pnl=self.pnl, entryTime=self.entry_time,
                    exitReason=reason, entryTimestamp=self.entry_timestamp,
                    exitTimestamp=self.exit_timestamp, basePrice=0.0 if missing else self.base_price,
                    entryStartIdx=-1 if missing else self.entry_start_idx,
                    events=[dict(e) for e in self.events])


def evaluate(candles, config: StrategyConfig, official_mfe=None):
    engine = S43REngine(config, official_mfe)
    for bar in candles:
        engine.step(bar)
    # app.js handles the empty-input case before the optional official-MFE gate.
    if not candles:
        engine.block_reason = None
    return engine.result()
