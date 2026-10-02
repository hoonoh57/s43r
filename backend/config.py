from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
ROOT = Path(__file__).resolve().parents[1]
class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['replay','record','paper','mock','live'] = 'replay'
    connection: Literal['mock','live'] = 'mock'
    condition_sequence: str = ''
    condition_name: str = ''
    allocation: int = Field(1000000, ge=10000, le=1000000000)
    max_positions: int = Field(3, ge=1, le=30)
    max_exposure: int = Field(3000000, ge=10000, le=10000000000)
    daily_loss: int = Field(100000, ge=1, le=1000000000)
    max_spread_bps: float = Field(50, ge=0, le=500)
    max_chase_bps: float = Field(30, ge=0, le=500)
    quote_age_ms: int = Field(3000, ge=100, le=30000)
    order_timeout_sec: int = Field(15, ge=1, le=300)
    early_enabled: bool = True
    early_macd: float = Field(.20, ge=0, le=5)
    base_rate: float = Field(5.5, gt=0, le=30)
    hard_stop: float = Field(-3, ge=-20, lt=0)
    cost_pct: float = Field(.25, ge=0, le=5)
    replay_speed: float = Field(30, ge=1, le=500)
    history_pages: int = Field(40, ge=2, le=200)
    def broker_mode(self): return self.mode in ('mock','live')
class SettingsFile:
    def __init__(self, folder): self.path = Path(folder)/'settings.json'
    def load(self): return Settings.model_validate_json(self.path.read_text(encoding='utf-8')) if self.path.exists() else Settings()
    def save(self, value):
        p=self.path.with_suffix('.tmp');p.write_text(value.model_dump_json(indent=2),encoding='utf-8');p.replace(self.path)
