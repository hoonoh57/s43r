const VARIANTS = ['S4.3-R', 'R2', 'R3'];
const COLORS = ['#5ddbd2', '#eac57c', '#63dca6'];
const $ = id => document.getElementById(id);

let backtestChart = null;
let seriesMap = {};

function setStatus(message, state = '') {
  const status = $('bt-status');
  status.textContent = message;
  status.dataset.state = state;
}

function initBacktestChart() {
  if (backtestChart) return true;
  const container = $('bt-chart-container');
  const charts = window.LightweightCharts;
  if (!container || !charts?.createChart || !charts.LineSeries) {
    setStatus('차트 라이브러리를 불러오지 못했습니다. 백테스트 결과 표시는 계속 사용할 수 있습니다.', 'warning');
    return false;
  }

  backtestChart = charts.createChart(container, {
    autoSize: true,
    height: 350,
    layout: {
      background: { type: charts.ColorType.Solid, color: '#121b27' },
      textColor: '#8191a7',
    },
    grid: {
      vertLines: { color: '#243141' },
      horzLines: { color: '#243141' },
    },
    rightPriceScale: { borderColor: '#243141' },
    timeScale: { timeVisible: true, secondsVisible: true },
  });
  VARIANTS.forEach((variant, index) => {
    seriesMap[variant] = backtestChart.addSeries(charts.LineSeries, {
      color: COLORS[index],
      lineWidth: 2,
      title: variant,
    });
  });
  return true;
}

function toChartTime(value, targetDate) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.floor(value > 1e12 ? value / 1000 : value);
  }
  const text = String(value ?? '').trim();
  const compactDateTime = text.match(/^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$/);
  if (compactDateTime) {
    const [, year, month, day, hour, minute, second] = compactDateTime;
    return Math.floor(Date.parse(`${year}-${month}-${day}T${hour}:${minute}:${second}Z`) / 1000);
  }
  if (/^\d{10,13}$/.test(text)) {
    const numeric = Number(text);
    return Math.floor(text.length === 13 ? numeric / 1000 : numeric);
  }

  const timeOnly = text.match(/^(\d{2}):?(\d{2}):?(\d{2})$/);
  if (timeOnly) {
    const date = String(targetDate);
    if (!/^\d{8}$/.test(date)) return null;
    const iso = `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`;
    return Math.floor(Date.parse(`${iso}T${timeOnly[1]}:${timeOnly[2]}:${timeOnly[3]}Z`) / 1000);
  }

  const parsed = Date.parse(text.includes(' ') ? text.replace(' ', 'T') : text);
  return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : null;
}

function formatNumber(value, fractionDigits = 0) {
  const number = Number(value);
  return Number.isFinite(number)
    ? number.toLocaleString('ko-KR', { maximumFractionDigits: fractionDigits })
    : '—';
}

function formatPercent(value, signed = false) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  const prefix = signed && number > 0 ? '+' : '';
  return `${prefix}${formatNumber(number, 2)}%`;
}

function metricRows() {
  return [
    ['누적 수익률 (%)', 'total_return_pct', metrics => formatPercent(metrics.total_return_pct, true)],
    ['최종 평가 자산 (원)', 'final_equity', metrics => `${formatNumber(metrics.final_equity)}원`],
    ['MDD (최대 낙폭 %)', 'mdd_pct', metrics => {
      const value = Number(metrics.mdd_pct);
      return Number.isFinite(value) ? `-${formatNumber(Math.abs(value))}%` : '—';
    }],
    ['승률 (Win Rate)', 'win_rate', metrics => `${formatPercent(metrics.win_rate)} (${formatNumber(metrics.win_count)}승 ${formatNumber(metrics.loss_count)}패)`],
    ['Profit Factor (손익비)', 'profit_factor', metrics => formatNumber(metrics.profit_factor, 2)],
    ['총 거래 횟수', 'total_trades', metrics => `${formatNumber(metrics.total_trades)}회`],
    ['평균 수익금 (원)', 'avg_win', metrics => `${formatNumber(metrics.avg_win)}원`],
    ['평균 손실금 (원)', 'avg_loss', metrics => `${formatNumber(metrics.avg_loss)}원`],
  ];
}

function renderMetrics(results) {
  const rows = metricRows();
  $('bt-metrics-table-body').innerHTML = rows.map(([label, key, formatter]) => {
    const cells = VARIANTS.map(variant => {
      const metrics = results?.[variant]?.metrics;
      return `<td>${metrics && metrics[key] !== undefined ? formatter(metrics) : '—'}</td>`;
    }).join('');
    return `<tr><td>${label}</td>${cells}</tr>`;
  }).join('');
}

function renderEquityCurves(results, targetDate) {
  if (!initBacktestChart()) return false;
  for (const variant of VARIANTS) {
    const curve = results?.[variant]?.equity_curve;
    const points = Array.isArray(curve) ? curve : [];
    const byTime = new Map();
    points.forEach(point => {
      const time = toChartTime(point?.time, targetDate);
      const value = Number(point?.value);
      if (time !== null && Number.isFinite(value)) byTime.set(time, { time, value });
    });
    const data = [...byTime.values()].sort((a, b) => a.time - b.time);
    seriesMap[variant].setData(data);
  }
  backtestChart.timeScale().fitContent();
  return true;
}

async function executeBacktestCompare() {
  const symbol = $('bt-symbol').value.trim();
  const date = $('bt-date').value.trim();
  const capital = Number($('bt-capital').value);
  const button = $('bt-run-btn');

  if (!symbol) return setStatus('종목 코드를 입력하세요.', 'error');
  if (!/^\d{8}$/.test(date)) return setStatus('대상 일자를 YYYYMMDD 형식으로 입력하세요.', 'error');
  if (!Number.isFinite(capital) || capital <= 0) return setStatus('초기 자본금은 0보다 큰 숫자여야 합니다.', 'error');

  button.disabled = true;
  setStatus('3개 전략 틱 시뮬레이션 계산 중...', 'loading');
  try {
    const response = await fetch('/api/backtest/run-compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol,
        target_date: date,
        initial_cash: capital,
        variants: VARIANTS,
        fee_bps: 20.0,
        slippage_bps: 1.5,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(typeof payload.detail === 'string' ? payload.detail : '백테스트 실행 실패');
    }
    if (!payload.results || typeof payload.results !== 'object') {
      throw new Error('백테스트 응답에 비교 결과가 없습니다.');
    }
    renderMetrics(payload.results);
    const chartReady = renderEquityCurves(payload.results, date);
    const sourceLabel = payload.data_source === 'synthetic'
      ? '합성 데이터 — 실거래 성과가 아닙니다.'
      : '로컬 데이터';
    setStatus(
      chartReady
        ? `완료되었습니다. (${sourceLabel})`
        : `백테스트는 완료되었지만 차트를 초기화하지 못했습니다. (${sourceLabel})`,
      chartReady ? 'success' : 'warning',
    );
  } catch (error) {
    setStatus(`오류: ${error instanceof Error ? error.message : String(error)}`, 'error');
  } finally {
    button.disabled = false;
  }
}

document.querySelector('[data-view="backtest"]')?.addEventListener('click', () => {
  requestAnimationFrame(() => {
    if (!backtestChart) initBacktestChart();
  });
});
$('bt-run-btn')?.addEventListener('click', executeBacktestCompare);
