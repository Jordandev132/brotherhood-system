"""Killshot configuration — spread-only engine."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


class KillshotConfig:
    """Spread-only configuration. No kill zone, no momentum, no directional."""

    def __init__(self):
        # Mode
        self.enabled: bool = _env("KILLSHOT_ENABLED", "true").lower() in ("true", "1", "yes")
        self.dry_run: bool = _env("KILLSHOT_DRY_RUN", "true").lower() in ("true", "1", "yes")

        # Bankroll
        # BUG FIX #45: bankroll_usd was defined but never read by the engine.
        # Sizing uses max_bet_usd; loss control uses daily_loss_cap_usd.
        # Kept for operator reference only — has no runtime effect.
        self.bankroll_usd: float = float(_env("KILLSHOT_BANKROLL_USD", "50"))
        self.max_bet_usd: float = float(_env("KILLSHOT_SPREAD_MAX_BET_USD", "20"))
        self.daily_loss_cap_usd: float = float(_env("KILLSHOT_DAILY_LOSS_CAP_USD", "15"))

        # Assets
        self.assets: list[str] = [a.strip() for a in _env("KILLSHOT_ASSETS", "bitcoin").split(",")]

        # Timeframes
        _tf_str = _env("KILLSHOT_TIMEFRAMES", "5m,15m")
        self.timeframes: list[str] = [t.strip() for t in _tf_str.split(",")]

        # Loop
        self.tick_interval_s: float = float(_env("KILLSHOT_TICK_INTERVAL_S", "0.1"))
        self.scan_interval_s: float = float(_env("KILLSHOT_SCAN_INTERVAL_S", "5"))

        # Wallet (live mode)
        self.private_key: str = _env("KILLSHOT_PRIVATE_KEY", "")
        self.clob_api_key: str = _env("KILLSHOT_CLOB_API_KEY", "")
        self.clob_api_secret: str = _env("KILLSHOT_CLOB_API_SECRET", "")
        self.clob_api_passphrase: str = _env("KILLSHOT_CLOB_API_PASSPHRASE", "")
        self.funder_address: str = _env("KILLSHOT_FUNDER_ADDRESS", "")
        self.signature_type: int = int(_env("KILLSHOT_SIGNATURE_TYPE", "2"))

        # Rust executor
        self.rust_executor_url: str = _env("KILLSHOT_RUST_EXECUTOR_URL", "http://127.0.0.1:9999")

        # Spread parameters
        self.spread_max_combined_cost: float = float(_env("KILLSHOT_SPREAD_MAX_COMBINED", "0.98"))
        self.spread_min_net_edge: float = float(_env("KILLSHOT_SPREAD_MIN_NET_EDGE", "0.01"))
        self.spread_entry_start_s: int = int(_env("KILLSHOT_SPREAD_ENTRY_START_S", "0"))
        self.spread_entry_end_s: int = int(_env("KILLSHOT_SPREAD_ENTRY_END_S", "120"))
        # BUG FIX #45: spread_min_leg_depth was defined but never read by the engine.
        # The engine uses spread_min_leg_shares for per-leg fill checks.
        # Kept for backward compat — has no runtime effect.
        self.spread_min_leg_depth: int = int(_env("KILLSHOT_SPREAD_MIN_LEG_DEPTH", "10"))

        # Per-leg fillability
        self.spread_min_leg_shares: int = int(_env("KILLSHOT_SPREAD_MIN_LEG_SHARES", "10"))
        # BUG FIX #45: spread_depth_levels was defined but never read by the engine.
        # The WS/REST book parsers always use top 5 levels hardcoded.
        # Kept for backward compat — has no runtime effect.
        self.spread_depth_levels: int = int(_env("KILLSHOT_SPREAD_DEPTH_LEVELS", "3"))
        self.spread_min_fill_ratio: float = float(_env("KILLSHOT_SPREAD_MIN_FILL_RATIO", "1.2"))
        self.spread_breaker_pause_s: int = int(_env("KILLSHOT_SPREAD_BREAKER_PAUSE_S", "120"))

        # Orphan handling
        self.orphan_process_interval_s: int = int(_env("KILLSHOT_ORPHAN_INTERVAL_S", "30"))
        self.orphan_max_attempts: int = int(_env("KILLSHOT_ORPHAN_MAX_ATTEMPTS", "20"))
        self.orphan_sell_retries: int = int(_env("KILLSHOT_ORPHAN_SELL_RETRIES", "5"))

        # Circuit breaker
        self.breaker_max_consec_fails: int = int(_env("KILLSHOT_BREAKER_MAX_FAILS", "3"))
        self.breaker_cooldown_s: int = int(_env("KILLSHOT_BREAKER_COOLDOWN_S", "120"))

        # Sweeper
        self.sweeper_interval_s: int = int(_env("KILLSHOT_SWEEPER_INTERVAL_S", "300"))
