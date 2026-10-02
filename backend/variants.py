"""S4.3-R 파생 버전. 원본 strategy.py(S43REngine)는 수정하지 않는다.
진입 로직은 원본과 동일하며, 익절 단계·비중·런너 규칙만 Spec 으로 바꾼다."""
from dataclasses import dataclass
import math
from .strategy import S43REngine


@dataclass(frozen=True)
class Spec:
    name: str
    label: str
    tiers: tuple      # ((설정 속성명, 비중 또는 None=cfg.tp_fraction), ...)
    same_bar: bool    # 다음 단계 익절이 앞 단계와 같은 봉에서 가능한가
    runner: str       # 'orig' = 원본 ATR/VWAP/시간 규칙, 'st' = ST 하락전환까지 보유


ORIG = Spec('S4.3-R', '원본: 1차 30% · 2차 30%(같은 봉 가능) · 런너 ATR/VWAP',
            (('tp1_pct', None), ('tp2_pct', None)), True, 'orig')
SPECS = {
    'S4.3-R': ORIG,
    'S4.3-R2': Spec('S4.3-R2', 'R2: 1차 30% · 잔량 70% ST 하락전환',
                    (('tp1_pct', .30),), True, 'st'),
    'S4.3-R3': Spec('S4.3-R3', 'R3: 1차 40% · 2차 30%(다음 봉부터) · 3차 30% ST 하락전환',
                    (('tp1_pct', .40), ('tp2_pct', .30)), False, 'st'),
}
NAMES = list(SPECS)


class VariantEngine(S43REngine):
    def __init__(self, config, official_mfe=None, spec=ORIG):
        super().__init__(config, official_mfe)
        self.spec = spec
        self.tp = []   # [(가격, 비중, 봉 index)]
        fr = [self._frac(f) for _, f in spec.tiers]
        if not all(0 < f < 1 for f in fr) or sum(fr) >= 1:
            raise ValueError('익절 비중 합은 1 미만이어야 합니다.')

    def _frac(self, f):
        return self.config.tp_fraction if f is None else f

    def _exit(self, b, reason):
        ep = self.entry_price
        part, rem = 0.0, 1.0
        for p, f, _ in self.tp:
            part += (p - ep) / ep * (f * 100)
            rem -= f
        self.pnl = part + (float(b['close']) - ep) / ep * (rem * 100)
        self.reason = reason
        self.closed = True
        self.exit_timestamp = b['timestamp']
        self._event('exit', b, rem, reason)

    def step(self, candle):
        from datetime import datetime, timedelta, timezone
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
                self._event('entry', b, 1.0, self.spec.name + '진입')
        if self.entered and b['timestamp'] > self.entry_timestamp:
            sp = self.spec
            self.runner_high = max(self.runner_high, float(b['high']))
            pnl = (c - self.entry_price) / self.entry_price * 100.0
            turn_down = v['jma'] < prev and prev >= prev2
            if pnl <= cfg.hard_stop_pct:
                self._exit(b, f'하드스탑({cfg.hard_stop_pct:.1f}%)')
            elif self.tp and pnl <= cfg.bep_pct:
                self._exit(b, '본전컷(BEP)')
            else:
                for i, (attr, f) in enumerate(sp.tiers):
                    if i < len(self.tp):
                        continue
                    if i and not sp.same_bar and self.tp[-1][2] >= self.index:
                        break
                    if pnl >= getattr(cfg, attr) and turn_down:
                        f = self._frac(f)
                        self.tp.append((c, f, self.index))
                        self._event('partial', b, f, f'{i + 1}차{round(f * 100)}%익절')
                    else:
                        break
                self.p1 = self.tp[0][0] if self.tp else None
                self.p2 = self.tp[1][0] if len(self.tp) > 1 else None
                done = len(self.tp) == len(sp.tiers)
                if sp.runner == 'orig':
                    atr = v['atr'] or (float(b['high']) - float(b['low']))
                    if done and c < self.runner_high - cfg.atr_trail_mult * atr:
                        self._exit(b, 'ATR동적트레일링컷')
                    elif v['trend'] == -1 or (self.tp and c < v['vwap'] * cfg.vwap_runner_cut):
                        self._exit(b, '추세이탈(런너청산)' if self.tp else 'ST하락(손절)')
                    elif date == cfg.target_date and time > cfg.exit_soft:
                        strong = v['trend'] == 1 and c >= v['vwap'] * cfg.vwap_extend
                        if not strong or time >= cfg.exit_hard:
                            self._exit(b, '추세연장마감(10:30)' if time >= cfg.exit_hard else '10:03시간종료')
                else:
                    if v['trend'] == -1:
                        self._exit(b, f'{len(self.tp) + 1}차 ST하락전환' if self.tp else 'ST하락(손절)')
                    elif date == cfg.target_date and time >= cfg.exit_hard:
                        self._exit(b, '10:30마감')
        return [dict(e) for e in self.events[n:]]


def engine_for(name=None):
    """None/'S4.3-R' -> 원본 S43REngine 그대로. 나머지 -> VariantEngine."""
    if not name or name == 'S4.3-R':
        return S43REngine
    spec = SPECS.get(name)
    if spec is None:
        raise ValueError(f'알 수 없는 전략 버전: {name}')
    return lambda cfg, official_mfe=None: VariantEngine(cfg, official_mfe, spec)
