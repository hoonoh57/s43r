"""Load local market ticks for strategy backtests."""

import csv
import glob
import json
import math
import re
from datetime import datetime, time
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
TOOLS_DATA_DIR = BASE_DIR / "tools"
TICKS_DATA_DIR = BASE_DIR / "ticks"

_PRICE_FIELDS = ("price", "close", "현재가", "체결가")
_TIME_FIELDS = ("time", "timestamp", "체결시간", "시간")
_DATE_FIELDS = ("date", "일자", "거래일")
_VOLUME_FIELDS = ("volume", "trde_qty", "qty", "거래량", "체결량")
_FILE_SUFFIXES = (".csv", ".jsonl", ".json")


def load_simulation_ticks(symbol: str, target_date: str) -> list[dict[str, Any]]:
    """Load a symbol/day from local CSV, JSONL, or CYBOS tick JSON data.

    When no matching local file exists, deterministic mock ticks are returned
    for UI and simulation development.
    """
    symbol = str(symbol).strip().upper()
    if len(symbol) == 7 and symbol[0] in "AJQ":
        symbol = symbol[1:]
    if not re.fullmatch(r"[0-9A-Z]{6}", symbol):
        raise ValueError("KRX 6자리 종목코드가 필요합니다.")

    day = _validate_date(target_date)
    files = _find_data_files(symbol, day)
    for path in files:
        ticks = _parse_data_file(path, day)
        if ticks:
            return ticks
    if files:
        raise ValueError(f"종목 {symbol}의 {day} 데이터 파일에서 유효한 틱을 찾지 못했습니다.")
    return _generate_mock_ticks(symbol, day)


def _validate_date(target_date: str) -> str:
    value = str(target_date).strip()
    if not re.fullmatch(r"\d{8}", value):
        raise ValueError("대상 일자는 YYYYMMDD 형식의 유효한 날짜여야 합니다.")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise ValueError("대상 일자는 YYYYMMDD 형식의 유효한 날짜여야 합니다.") from exc


def _find_data_files(symbol: str, target_date: str) -> list[Path]:
    escaped_symbol = glob.escape(symbol)
    directories = (TICKS_DATA_DIR, DATA_DIR, TOOLS_DATA_DIR)
    patterns: list[str] = []
    for suffix in _FILE_SUFFIXES:
        patterns.extend((
            f"*{escaped_symbol}*{target_date}*{suffix}",
            f"*{target_date}*{escaped_symbol}*{suffix}",
        ))
    patterns.append(f"{escaped_symbol}.csv")

    matches: dict[Path, None] = {}
    for directory in directories:
        for pattern in patterns:
            for filename in glob.glob(str(directory / pattern)):
                path = Path(filename)
                if path.is_file():
                    matches[path] = None
    return list(matches)


def _parse_data_file(filepath: Path, target_date: str) -> list[dict[str, Any]]:
    if filepath.suffix.lower() == ".csv":
        return _parse_csv_ticks(filepath, target_date)
    if filepath.suffix.lower() == ".jsonl":
        return _parse_jsonl_ticks(filepath, target_date)
    if filepath.suffix.lower() == ".json":
        return _parse_json_ticks(filepath, target_date)
    return []


def _parse_csv_ticks(filepath: Path, target_date: str) -> list[dict[str, Any]]:
    parsed = []
    with filepath.open(mode="r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            tick = _tick_from_mapping(row, target_date)
            if tick is not None:
                parsed.append(tick)
    return _sorted_ticks(parsed)


def _parse_jsonl_ticks(filepath: Path, target_date: str) -> list[dict[str, Any]]:
    parsed = []
    with filepath.open(mode="r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{filepath.name}:{line_number} JSONL 항목은 객체여야 합니다.")
            tick = _tick_from_mapping(value, target_date)
            if tick is not None:
                parsed.append(tick)
    return _sorted_ticks(parsed)


def _parse_json_ticks(filepath: Path, target_date: str) -> list[dict[str, Any]]:
    with filepath.open(mode="r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    rows = payload.get("ticks") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"{filepath.name} 파일에 틱 목록이 없습니다.")

    parsed = []
    for row in rows:
        if isinstance(row, dict):
            tick = _tick_from_mapping(row, target_date)
        elif isinstance(row, (list, tuple)) and len(row) >= 3:
            tick = _tick_from_cybos_row(row, target_date)
        else:
            tick = None
        if tick is not None:
            parsed.append(tick)
    return _sorted_ticks(parsed)


def _tick_from_mapping(row: dict[str, Any], target_date: str) -> dict[str, Any] | None:
    normalized = {
        str(key).strip().casefold(): value
        for key, value in row.items()
        if key is not None
    }
    price_value = _first_value(normalized, _PRICE_FIELDS)
    time_value = _first_value(normalized, _TIME_FIELDS)
    date_value = _first_value(normalized, _DATE_FIELDS)
    volume_value = _first_value(normalized, _VOLUME_FIELDS)
    return _make_tick(time_value, price_value, target_date, date_value, volume_value)


def _tick_from_cybos_row(row: list[Any] | tuple[Any, ...], target_date: str) -> dict[str, Any] | None:
    tick_date, tick_time, price = row[:3]
    time_text = re.sub(r"\D", "", str(tick_time))
    if len(time_text) == 4:
        time_text += "00"
    elif len(time_text) != 6:
        return None
    combined_time = f"{tick_date}{time_text}"
    volume = row[3] if len(row) > 3 else None
    return _make_tick(combined_time, price, target_date, volume_value=volume)


def _first_value(row: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    for candidate in candidates:
        value = row.get(candidate.casefold())
        if value is not None and str(value).strip():
            return value
    return None


def _make_tick(
    time_value: Any,
    price_value: Any,
    target_date: str,
    date_value: Any = None,
    volume_value: Any = None,
) -> dict[str, Any] | None:
    if time_value is None or price_value is None:
        return None

    normalized_time = _normalize_time(time_value, target_date, date_value)
    if normalized_time is None:
        return None

    try:
        price = abs(float(str(price_value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None
    try:
        volume = abs(float(str(volume_value).replace(",", "").strip())) if volume_value is not None else 1.0
    except (TypeError, ValueError):
        return None
    if not math.isfinite(volume):
        return None
    return {"time": normalized_time, "price": price, "volume": volume}


def _normalize_time(time_value: Any, target_date: str, date_value: Any = None) -> str | None:
    value = str(time_value).strip()
    date_text = re.sub(r"\D", "", str(date_value or ""))
    if len(date_text) != 8:
        date_text = target_date

    digits = re.sub(r"\D", "", value)
    if len(digits) in (12, 14) and digits[:8].isdigit():
        return digits[:14].ljust(14, "0")
    if len(digits) in (4, 6) and digits == value:
        return f"{date_text}{digits.ljust(6, '0')}"

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
    if parsed is not None:
        return parsed.strftime("%Y%m%d%H%M%S")

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
        try:
            parsed_time = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if fmt.startswith("%Y"):
            return parsed_time.strftime("%Y%m%d%H%M%S")
        return datetime.combine(
            datetime.strptime(date_text, "%Y%m%d").date(),
            time(parsed_time.hour, parsed_time.minute, parsed_time.second),
        ).strftime("%Y%m%d%H%M%S")
    return None


def _sorted_ticks(ticks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(ticks, key=lambda tick: tick["time"])


def _generate_mock_ticks(symbol: str, target_date: str) -> list[dict[str, Any]]:
    """Generate deterministic 360-trade bars every five minutes for a session."""
    del symbol
    current_price = 10000.0
    step_delta = [10, -10, 20, -15, 30, -10, 50, -30, 20, 10, -40, 60]
    mock_data = []

    for index, minute_of_day in enumerate(range(9 * 60, 15 * 60 + 31, 5)):
        current_price += step_delta[index % len(step_delta)]
        hour, minute = divmod(minute_of_day, 60)
        timestamp = f"{target_date}{hour:02d}{minute:02d}00"
        mock_data.extend(
            {"time": timestamp, "price": round(current_price, 0), "volume": 1.0, "synthetic": True}
            for _ in range(360)
        )
    return mock_data
