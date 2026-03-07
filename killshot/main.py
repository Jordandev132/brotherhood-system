"""Killshot — spread-only engine for crypto up/down markets.

Usage:
    cd ~/polymarket-bot && .venv/bin/python -m killshot.main
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from bot.config import Config as BotConfig
from bot.price_cache import PriceCache
from bot.binance_feed import BinanceFeed
from bot.snipe.window_tracker import WindowTracker

from killshot.config import KillshotConfig
from killshot.clob_ws import ClobWS
from killshot.engine import KillshotEngine
from killshot.tracker import PaperTracker

log = logging.getLogger("killshot")

# ── Asset detection ─────────────────────────────────────────────
_ASSET_KEYWORDS = {
    "bitcoin": ("bitcoin up or down",),
    "ethereum": ("ethereum up or down",),
    "solana": ("solana up or down",),
    "xrp": ("xrp up or down",),
}
_ASSET_SHORT = {
    "bitcoin": "btc", "ethereum": "eth", "solana": "sol", "xrp": "xrp",
}


def _detect_asset(question: str) -> str | None:
    q = question.lower()
    for asset, keywords in _ASSET_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return asset
    return None


@dataclass
class MarketWindow:
    market_id: str
    question: str
    asset: str
    raw: dict[str, Any]


_INTERVAL_MAP = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


def _scan_markets(assets: list[str], interval_s: int, tag: str) -> list[MarketWindow]:
    """Scan Gamma + CLOB for active crypto up/down markets.

    Args:
        assets: ["bitcoin", "ethereum", ...]
        interval_s: 300 for 5m, 900 for 15m, etc.
        tag: "5m" or "15m" (used in Gamma slug)
    """
    now = time.time()
    current_ts = int(now // interval_s) * interval_s
    intervals = [current_ts, current_ts + interval_s]

    results: list[MarketWindow] = []
    seen: set[str] = set()

    with httpx.Client(timeout=8) as client:
        for ts in intervals:
            for asset in assets:
                coin = _ASSET_SHORT.get(asset)
                if not coin:
                    continue
                slug = f"{coin}-updown-{tag}-{ts}"
                try:
                    resp = client.get(
                        "https://gamma-api.polymarket.com/markets",
                        params={"slug": slug},
                    )
                    if resp.status_code != 200:
                        continue
                    for m in resp.json():
                        cid = m.get("conditionId") or m.get("condition_id", "")
                        if not cid or cid in seen or m.get("closed"):
                            continue
                        clob_resp = client.get(f"https://clob.polymarket.com/markets/{cid}")
                        if clob_resp.status_code != 200:
                            continue
                        clob_market = clob_resp.json()
                        if not clob_market.get("accepting_orders"):
                            continue
                        question = clob_market.get("question", "")
                        detected = _detect_asset(question)
                        if not detected or detected not in assets:
                            continue
                        seen.add(cid)
                        results.append(MarketWindow(
                            market_id=clob_market.get("condition_id", cid),
                            question=question[:120],
                            asset=detected,
                            raw=clob_market,
                        ))
                except Exception as e:
                    log.debug("Scan error %s/%s/%d: %s", asset, tag, ts, str(e)[:80])

    return results


# ── Signal handling ─────────────────────────────────────────────
_running = True


def _signal_handler(sig, _frame):
    global _running
    log.info("Shutdown signal (sig=%s)", sig)
    _running = False


def _setup_logging() -> None:
    fmt = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt, datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


# ── Preflight gate ──────────────────────────────────────────────

def _preflight(clob_client, cfg) -> None:
    """Verify wallet balance + signing before going live."""
    from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

    # Balance check
    try:
        params = BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=cfg.signature_type,
        )
        bal = clob_client.get_balance_allowance(params)
        usdc = float(bal.get("balance", 0)) / 1e6
        log.info("Preflight: USDC = $%.2f", usdc)
        if usdc < 1.0:
            log.critical("Preflight FAILED: $%.2f < $1.00", usdc)
            sys.exit(1)
    except Exception as e:
        log.critical("Preflight FAILED: %s", str(e)[:150])
        sys.exit(1)

    log.info("Preflight: PASSED")


# ── Main ────────────────────────────────────────────────────────

def main() -> None:
    global _running

    _setup_logging()
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    cfg = KillshotConfig()
    bot_cfg = BotConfig()

    log.info("=" * 50)
    log.info("KILLSHOT — Spread Engine")
    log.info("=" * 50)
    log.info("Mode:     %s", "PAPER" if cfg.dry_run else "LIVE")
    log.info("Max bet:  $%.0f", cfg.max_bet_usd)
    log.info("Assets:   %s", ", ".join(cfg.assets))
    log.info("Edge:     %.1f¢ min | Combined < %.0f¢",
             cfg.spread_min_net_edge * 100, cfg.spread_max_combined_cost * 100)
    # BUG FIX #41: Was logging spread_min_leg_depth (unused by engine) instead
    # of spread_min_leg_shares (the value the engine actually enforces).
    log.info("Depth:    %d shares min per leg", cfg.spread_min_leg_shares)
    log.info("Timeframes: %s", ", ".join(cfg.timeframes))
    log.info("=" * 50)

    # Safety: live mode needs key
    if not cfg.dry_run and not cfg.private_key:
        log.critical("LIVE MODE requires KILLSHOT_PRIVATE_KEY")
        sys.exit(1)

    # Init shared components
    from bot.snipe import clob_book
    clob_book.init("https://clob.polymarket.com")

    # CLOB client (live only)
    clob_client = None
    if not cfg.dry_run and cfg.private_key:
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
            clob_client = ClobClient(
                "https://clob.polymarket.com",
                key=cfg.private_key,
                chain_id=137,
                funder=cfg.funder_address or None,
                signature_type=cfg.signature_type,
            )
            if cfg.clob_api_key:
                clob_client.set_api_creds(ApiCreds(
                    api_key=cfg.clob_api_key,
                    api_secret=cfg.clob_api_secret,
                    api_passphrase=cfg.clob_api_passphrase,
                ))
            clob_client.get_ok()
            log.info("CLOB client connected — LIVE mode")
            _preflight(clob_client, cfg)
        except Exception:
            log.exception("CLOB client FAILED — forcing paper mode")
            clob_client = None
            cfg.dry_run = True

    price_cache = PriceCache()
    price_cache.preload_from_disk()

    # Chainlink WS
    from killshot.chainlink_ws import ChainlinkWS
    chainlink_ws = ChainlinkWS()
    chainlink_ws.start()

    # CLOB orderbook WS
    clob_ws = ClobWS()
    clob_ws.start()

    # Binance feed
    binance_feed = BinanceFeed(bot_cfg, price_cache)
    window_tracker = WindowTracker(bot_cfg, price_cache)
    tracker = PaperTracker()

    engine = KillshotEngine(cfg, price_cache, tracker, clob_client=clob_client,
                            chainlink_ws=chainlink_ws, clob_ws=clob_ws,
                            binance_feed=binance_feed)

    # Wire WS callback → engine
    clob_ws._on_book_update = engine.on_book_update

    # Start Binance
    loop = asyncio.new_event_loop()
    loop.run_until_complete(binance_feed.start())
    log.info("Binance feed started")

    # Wait for price data
    log.info("Waiting for prices...")
    for _ in range(30):
        if chainlink_ws.get_price("bitcoin") or price_cache.get_price("bitcoin"):
            break
        time.sleep(1)

    btc = price_cache.get_price("bitcoin")
    if btc:
        log.info("BTC: $%.2f — ready", btc)

    last_scan = 0.0
    last_status = 0.0
    last_cleanup = 0.0

    log.info("Main loop starting...")

    while _running:
        try:
            now = time.time()
            binance_feed.ensure_alive()

            # Market scan
            if now - last_scan > cfg.scan_interval_s:
                markets = []
                for tf in cfg.timeframes:
                    interval_s = _INTERVAL_MAP.get(tf, 300)
                    markets.extend(_scan_markets(cfg.assets, interval_s, tf))
                if markets:
                    window_tracker.update(markets)
                    active = len(window_tracker.all_active_windows())
                    log.info("Scan: %d markets, %d active", len(markets), active)

                    # Update WS subscriptions
                    token_ids = set()
                    for w in window_tracker.all_active_windows():
                        if w.up_token_id:
                            token_ids.add(w.up_token_id)
                        if w.down_token_id:
                            token_ids.add(w.down_token_id)
                    if token_ids:
                        clob_ws.update_subscriptions(token_ids)

                last_scan = now

            # Engine tick
            engine.tick(window_tracker.all_active_windows())

            # Resolve trades
            resolved = tracker.resolve_trades(price_cache, clob_ws=clob_ws)
            if resolved:
                engine.report_resolved(resolved)

            # Cleanup (hourly)
            if now - last_cleanup > 3600:
                engine.cleanup_expired()
                last_cleanup = now

            # Status (every 10s)
            if now - last_status > 10:
                tracker.write_status(engine_state=engine.get_engine_state())
                last_status = now

            time.sleep(cfg.tick_interval_s)

        except KeyboardInterrupt:
            break
        except Exception:
            log.exception("Tick error")
            time.sleep(5)

    log.info("Shutting down...")
    clob_ws.stop()
    chainlink_ws.stop()
    tracker.write_status()
    price_cache.save_candles()
    binance_feed._running = False
    loop.close()
    log.info("Killshot stopped.")


if __name__ == "__main__":
    main()
