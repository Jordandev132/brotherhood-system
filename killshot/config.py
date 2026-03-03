"""Killshot configuration — reads from shared .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class KillshotConfig:
    """All Killshot parameters — read from .env with sane paper-mode defaults."""

    # Mode
    dry_run: bool = _env("KILLSHOT_DRY_RUN", "true").lower() in ("true", "1", "yes")
    enabled: bool = _env("KILLSHOT_ENABLED", "true").lower() in ("true", "1", "yes")

    # Bankroll
    bankroll_usd: float = float(_env("KILLSHOT_BANKROLL_USD", "50"))
    max_bet_usd: float = float(_env("KILLSHOT_MAX_BET_USD", "5"))
    daily_loss_cap_usd: float = float(_env("KILLSHOT_DAILY_LOSS_CAP_USD", "15"))

    # Direction detection — minimum spot price delta to consider direction "locked"
    direction_threshold: float = float(_env("KILLSHOT_DIRECTION_THRESHOLD", "0.0010"))

    # Entry pricing — simulated maker limit order price range
    entry_price_min: float = float(_env("KILLSHOT_ENTRY_PRICE_MIN", "0.60"))
    entry_price_max: float = float(_env("KILLSHOT_ENTRY_PRICE_MAX", "0.75"))

    # Kill zone — how many seconds before window close to evaluate
    window_seconds: int = int(_env("KILLSHOT_WINDOW_SECONDS", "35"))
    min_window_seconds: int = int(_env("KILLSHOT_MIN_WINDOW_SECONDS", "0"))

    # Assets (comma-separated)
    assets_str: str = _env("KILLSHOT_ASSETS", "bitcoin")

    # Loop intervals
    tick_interval_s: float = float(_env("KILLSHOT_TICK_INTERVAL_S", "0.1"))
    scan_interval_s: float = float(_env("KILLSHOT_SCAN_INTERVAL_S", "60"))

    # Separate wallet (live mode only — unused in paper)
    private_key: str = _env("KILLSHOT_PRIVATE_KEY", "")
    clob_api_key: str = _env("KILLSHOT_CLOB_API_KEY", "")
    clob_api_secret: str = _env("KILLSHOT_CLOB_API_SECRET", "")
    clob_api_passphrase: str = _env("KILLSHOT_CLOB_API_PASSPHRASE", "")
    funder_address: str = _env("KILLSHOT_FUNDER_ADDRESS", "")

    # Rust executor URL (empty = disabled, Python-only mode)
    rust_executor_url: str = _env("KILLSHOT_RUST_EXECUTOR_URL", "http://127.0.0.1:9999")

    # Momentum (early-entry strategy)
    momentum_enabled: bool = _env("KILLSHOT_MOMENTUM_ENABLED", "false").lower() in ("true", "1", "yes")
    momentum_entry_start_s: int = int(_env("KILLSHOT_MOMENTUM_ENTRY_START_S", "30"))
    momentum_entry_end_s: int = int(_env("KILLSHOT_MOMENTUM_ENTRY_END_S", "60"))
    momentum_entry_price_min: float = float(_env("KILLSHOT_MOMENTUM_ENTRY_PRICE_MIN", "0.45"))
    momentum_entry_price_max: float = float(_env("KILLSHOT_MOMENTUM_ENTRY_PRICE_MAX", "0.55"))
    momentum_max_bet_usd: float = float(_env("KILLSHOT_MOMENTUM_MAX_BET_USD", "5"))
    momentum_prev_candle_threshold: float = float(_env("KILLSHOT_MOMENTUM_PREV_CANDLE_THRESHOLD", "0.0005"))
    momentum_confirm_threshold: float = float(_env("KILLSHOT_MOMENTUM_CONFIRM_THRESHOLD", "0.0003"))
    momentum_flow_min_strength: float = float(_env("KILLSHOT_MOMENTUM_FLOW_MIN_STRENGTH", "0.3"))
    momentum_fill_timeout_s: int = int(_env("KILLSHOT_MOMENTUM_FILL_TIMEOUT_S", "30"))
    momentum_min_signals: int = int(_env("KILLSHOT_MOMENTUM_MIN_SIGNALS", "2"))

    # Spread capture (both-sides guaranteed profit)
    spread_enabled: bool = _env("KILLSHOT_SPREAD_ENABLED", "false").lower() in ("true", "1", "yes")
    spread_max_combined_cost: float = float(_env("KILLSHOT_SPREAD_MAX_COMBINED", "0.97"))
    spread_max_bet_usd: float = float(_env("KILLSHOT_SPREAD_MAX_BET_USD", "5"))
    spread_entry_start_s: int = int(_env("KILLSHOT_SPREAD_ENTRY_START_S", "15"))
    spread_entry_end_s: int = int(_env("KILLSHOT_SPREAD_ENTRY_END_S", "60"))

    @property
    def assets(self) -> list[str]:
        return [a.strip() for a in self.assets_str.split(",")]
