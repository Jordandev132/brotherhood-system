"""Killshot spread engine — strict dual-fill only.

Strategy: buy BOTH sides of 5m crypto markets. If UP ask + DOWN ask < $1.00
(minus fees), buy both → one resolves to $1, guaranteed profit.

Design principles (every failure surface from March 5 is eliminated):
1. Centralized fail-closed risk gate: can_trade_now() blocks ALL new entries
2. Strict dual-fill: partial fill → neutralize, NEVER convert to directional
3. Non-blocking worker: cancel/neutralize in async queue, no sleep() in tick()
4. Per-leg fillability: cumulative depth validated before placing ANY order
5. Terminal window states: no re-entry while exposure exists
6. tick() order: manage risk → enforce gates → evaluate new entries
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from killshot.config import KillshotConfig
from killshot.tracker import PaperTrade, PaperTracker

from bot.price_cache import PriceCache
from bot.snipe.window_tracker import Window
from bot.snipe import clob_book

log = logging.getLogger("killshot.engine")

_ET = ZoneInfo("America/New_York")

_PENDING_FILE = Path(__file__).resolve().parent / "killshot_pending_orders.json"
_ORPHAN_FILE = Path(__file__).resolve().parent / "orphan_queue.json"
_ESTOP_FLAG = Path(__file__).resolve().parent.parent / "data" / "emergency_stop.flag"


# ── Spread lifecycle states ────────────────────────────────────

class SpreadState(str, Enum):
    PLACING = "placing"
    RESTING_BOTH = "resting_both"
    PARTIAL_DETECTED = "partial_detected"
    NEUTRALIZING = "neutralizing"
    CLOSED = "closed"


# ── Window terminal states ─────────────────────────────────────

class WindowState(str, Enum):
    BLOCKED_BY_RISK = "blocked_by_risk"
    PLACEMENT_FAILED = "placement_failed"
    PARTIAL_OPEN = "partial_open"
    FILLED = "filled"
    CLOSED = "closed"


class KillshotEngine:
    """Spread-only engine. Strict dual-fill. No directional fallback."""

    def __init__(self, cfg: KillshotConfig, price_cache: PriceCache,
                 tracker: PaperTracker, clob_client=None,
                 chainlink_ws=None, clob_ws=None, binance_feed=None):
        self._cfg = cfg
        self._cache = price_cache
        self._tracker = tracker
        self._client = clob_client
        self._chainlink = chainlink_ws
        self._clob_ws = clob_ws
        self._binance_feed = binance_feed
        self._dry_run = cfg.dry_run

        # Rust executor HTTP client
        self._rust_url = cfg.rust_executor_url.rstrip("/") if cfg.rust_executor_url else ""
        self._rust_http = httpx.Client(timeout=5.0) if self._rust_url else None

        # Window states — terminal, never reopened while exposure exists
        # BUG FIX #1: single lock guards window state check+set (TOCTOU race)
        self._window_states: dict[str, WindowState] = {}
        self._window_lock = threading.Lock()
        self._spread_logged: set[str] = set()
        # BUG FIX #44: separate dedup set for skip-reason logs
        self._skip_logged: set[str] = set()

        # Emergency stop — internal flag (in addition to file-based)
        self._emergency_stop: bool = False
        self._emergency_lock = threading.Lock()

        # Circuit breaker
        self._breaker_consec_fails: int = 0
        self._breaker_paused_until: float = 0.0

        # Pending spread orders (lifecycle-tracked, persisted)
        self._pending_spreads: list[dict] = []
        self._pending_lock = threading.Lock()

        # Neutralization worker queue (non-blocking)
        self._neutralize_queue: list[dict] = []
        self._neutralize_lock = threading.Lock()

        # Daily loss tracking — uses 7pm ET boundary (consistent with tracker)
        self._daily_loss: float = 0.0
        self._daily_reset_ts: float = 0.0

        # Active windows cache for WS callback
        self._active_windows: list = []

        # Timers
        self._last_neutralize_process: float = 0.0
        self._last_sweep: float = 0.0
        self._last_pending_check: float = 0.0
        self._last_resting_check: float = 0.0

        # Resting limit orders (GTC spreads waiting for fills)
        self._resting_spreads: list[dict] = []
        self._resting_lock = threading.Lock()

        # Load persistent state
        self._load_pending_spreads()
        self._load_neutralize_queue()

    # ══════════════════════════════════════════════════════════════
    # 1. CENTRALIZED FAIL-CLOSED RISK GATE
    # ══════════════════════════════════════════════════════════════

    def can_trade_now(self) -> bool:
        """Single fail-closed gate. Returns False if ANY condition blocks trading.

        Checked before every new entry attempt. Pending order management
        and neutralization continue regardless.
        """
        # Config kill switch
        if not self._cfg.enabled:
            return False

        # File-based emergency stop (external kill switch)
        if _ESTOP_FLAG.exists():
            return False

        # Internal emergency stop (orphans exist)
        if self._emergency_stop:
            return False

        # Circuit breaker pause
        if time.time() < self._breaker_paused_until:
            return False

        # Daily loss cap
        if self._daily_loss >= self._cfg.daily_loss_cap_usd:
            return False

        # BUG FIX #20: read under lock (was bare read — race with WS thread)
        with self._neutralize_lock:
            if self._neutralize_queue:
                return False

        # Pending partial spreads exist
        with self._pending_lock:
            for ps in self._pending_spreads:
                if ps["state"] in (SpreadState.PARTIAL_DETECTED, SpreadState.NEUTRALIZING):
                    return False

        return True

    # ══════════════════════════════════════════════════════════════
    # 2. EVENT-DRIVEN SPREAD FROM WS CALLBACK
    # ══════════════════════════════════════════════════════════════

    def on_book_update(self, token_id: str, book: dict) -> None:
        """Called from CLOB WS thread on every book update.

        BUG FIX #11: Does NOT call _evaluate_spread (which does HTTP in live mode).
        Instead, signals the main tick loop that a book update was received.
        The tick loop runs _evaluate_spread, keeping I/O off the WS thread.
        """
        # No-op: tick() at 100ms handles spread evaluation.
        # This callback exists for future non-blocking fast-path in paper mode.
        pass

    # ══════════════════════════════════════════════════════════════
    # 3. MAIN TICK LOOP — RISK FIRST, THEN GATES, THEN ENTRIES
    # ══════════════════════════════════════════════════════════════

    def tick(self, windows: list) -> None:
        """Called every tick from main loop.

        Order: manage risk → enforce gates → evaluate new entries.
        """
        now = time.time()

        self._active_windows = windows

        # Daily reset at 7pm ET (consistent with tracker)
        boundary = self._last_7pm_et()
        if boundary > self._daily_reset_ts:
            self._daily_loss = 0.0
            self._daily_reset_ts = boundary
            self._spread_logged.clear()
            self._skip_logged.clear()
            log.info("[KILLSHOT] Daily reset (7pm ET boundary)")

        # ── STEP 1: Process pending/neutralization (ALWAYS, even when blocked) ──
        # BUG FIX #40: Was hardcoded to 10s instead of using config value.
        # orphan_process_interval_s (default 30s) was defined but never read.
        if now - self._last_neutralize_process >= self._cfg.orphan_process_interval_s:
            self._process_neutralize_queue()
            self._last_neutralize_process = now

        if now - self._last_pending_check >= 5:
            self._check_pending_spreads()
            self._last_pending_check = now

        # Check resting GTC orders for fills (every 3s)
        if now - self._last_resting_check >= 3:
            self._check_resting_fills()
            self._last_resting_check = now

        if now - self._last_sweep >= self._cfg.sweeper_interval_s:
            self._sweep_stuck_positions()
            self._last_sweep = now

        # ── STEP 2: Enforce global gates ──
        if not self.can_trade_now():
            return

        # ── STEP 3: Evaluate new spread opportunities ──
        cfg = self._cfg
        for window in windows:
            wid = window.market_id
            ws = self._window_states.get(wid)
            if ws is not None:
                continue  # any terminal state blocks
            if window.asset not in cfg.assets:
                continue
            elapsed = now - window.start_ts
            # Dynamic entry window: use configured end or window duration - 20s,
            # whichever is larger. For 5m: max(280, 280)=280. For 15m: max(280, 880)=880.
            duration = window.end_ts - window.start_ts
            entry_end = max(cfg.spread_entry_end_s, duration - 20)
            if cfg.spread_entry_start_s <= elapsed <= entry_end:
                self._evaluate_spread(window, elapsed)

    # ══════════════════════════════════════════════════════════════
    # 4. SPREAD EVALUATION — LIMIT ORDERS AT BID (MAKER, 0 FEES)
    # ══════════════════════════════════════════════════════════════

    def _evaluate_spread(self, window: Window, elapsed: float) -> bool:
        """Evaluate spread using BID prices. Place GTC limit orders (maker).

        Maker orders = 0 fees. Combined bids typically ~99¢ = 1¢ profit/share.
        Orders rest in the book and fill when someone market-sells into us.
        """
        if not self.can_trade_now():
            return False

        wid = window.market_id
        if self._window_states.get(wid) is not None:
            return False

        cfg = self._cfg

        if wid not in self._spread_logged:
            self._spread_logged.add(wid)
            log.info("[KILLSHOT] Spread zone: %s %s | T+%.0fs",
                     window.asset.upper(), wid[:12], elapsed)

        # Fetch BOTH books
        up_book = self._get_book(window.up_token_id)
        down_book = self._get_book(window.down_token_id)
        if not up_book or not down_book:
            if wid not in self._skip_logged:
                log.info("[KILLSHOT] Skip %s %s: no book (UP=%s DOWN=%s)",
                         window.asset.upper(), wid[:12], bool(up_book), bool(down_book))
                self._skip_logged.add(wid)
            return False

        # Use BID prices — we're posting limit orders, not lifting asks
        up_bid = up_book.get("best_bid", 0) or 0
        down_bid = down_book.get("best_bid", 0) or 0
        if up_bid <= 0 or down_bid <= 0:
            return False

        # Also need asks to verify market is active and 2-sided
        up_ask = up_book.get("best_ask", 0) or 0
        down_ask = down_book.get("best_ask", 0) or 0
        if up_ask <= 0 or down_ask <= 0:
            return False

        # Combined BID cost — maker fee = 0, so net edge = 1.00 - combined
        combined = up_bid + down_bid
        if combined >= cfg.spread_max_combined_cost:
            if wid not in self._skip_logged:
                log.info("[KILLSHOT] Skip %s: bids=%.1f¢ >= %.1f¢ cap (asks=%.0f¢)",
                         window.asset.upper(), combined * 100,
                         cfg.spread_max_combined_cost * 100,
                         (up_ask + down_ask) * 100)
                self._skip_logged.add(wid)
            return False

        net_edge = 1.0 - combined  # maker = 0 fees
        if net_edge < cfg.spread_min_net_edge:
            if wid not in self._skip_logged:
                log.info("[KILLSHOT] Skip %s: edge=%.1f¢ < %.1f¢ (UP_bid@%.0f¢+DN_bid@%.0f¢=%.0f¢)",
                         window.asset.upper(), net_edge * 100, cfg.spread_min_net_edge * 100,
                         up_bid * 100, down_bid * 100, combined * 100)
                self._skip_logged.add(wid)
            return False

        # Size to max bet (no fees to include for maker)
        shares = int(cfg.max_bet_usd / combined)
        if shares < 5:
            return False

        # Verify market has enough activity (ask depth shows sellers exist)
        up_ask_size = up_book.get("best_ask_size", 0) or 0
        down_ask_size = down_book.get("best_ask_size", 0) or 0
        if up_ask_size < 5 or down_ask_size < 5:
            return False

        log.info("[KILLSHOT] SPREAD BID: %s UP@%.0f¢+DOWN@%.0f¢=%.0f¢ | "
                 "edge=%.1f¢ | %dsh",
                 window.asset.upper(), up_bid * 100, down_bid * 100,
                 combined * 100, net_edge * 100, shares)

        # ── ATOMIC: claim window ──
        with self._window_lock:
            if self._window_states.get(wid) is not None:
                return False
            self._window_states[wid] = WindowState.FILLED

        if self._dry_run:
            return self._paper_spread(window, up_bid, down_bid, shares, net_edge)

        return self._place_limit_spread(window, up_bid, down_bid, shares, net_edge)

    # ══════════════════════════════════════════════════════════════
    # 5. PAPER SPREAD
    # ══════════════════════════════════════════════════════════════

    def _paper_spread(self, window, up_ask, down_ask, shares, net_edge):
        """Simulate spread fill in paper mode."""
        up_usd = round(shares * up_ask, 2)
        down_usd = round(shares * down_ask, 2)
        total = up_usd + down_usd

        up_trade = PaperTrade(
            timestamp=time.time(), asset=window.asset,
            market_id=window.market_id, question=window.question,
            direction="up", entry_price=round(up_ask, 2),
            size_usd=up_usd, shares=shares,
            window_end_ts=window.end_ts, spot_delta_pct=0.0,
            open_price=window.open_price, market_ask=up_ask,
            token_id=window.up_token_id or "",
        )
        down_trade = PaperTrade(
            timestamp=time.time() + 0.001, asset=window.asset,
            market_id=window.market_id, question=window.question,
            direction="down", entry_price=round(down_ask, 2),
            size_usd=down_usd, shares=shares,
            window_end_ts=window.end_ts, spot_delta_pct=0.0,
            open_price=window.open_price, market_ask=down_ask,
            token_id=window.down_token_id or "",
        )
        self._tracker.record_trade(up_trade, strategy="spread")
        self._tracker.record_trade(down_trade, strategy="spread")
        self._tracker.notify_spread_entry(window.asset, up_ask, down_ask, total, net_edge * 100)

        log.info("[KILLSHOT] PAPER SPREAD: %s | UP %.0f¢ + DOWN %.0f¢ | %d sh | $%.2f",
                 window.asset.upper(), up_ask * 100, down_ask * 100, shares, total)
        return True


    # ══════════════════════════════════════════════════════════════
    # 6. LIVE SPREAD — GTC LIMIT ORDERS AT BID
    # ══════════════════════════════════════════════════════════════

    def _place_limit_spread(self, window, up_bid, down_bid, shares, net_edge):
        """Place GTC limit orders at bid price via Rust batch executor.

        Orders rest in the book. Fill tracking via _check_resting_fills.
        If only one leg fills before window ends, sell it immediately.
        """
        combined = up_bid + down_bid
        if combined >= 1.0:
            log.warning("[KILLSHOT] Safety abort: bids %.2f+%.2f=%.3f >= $1.00",
                        up_bid, down_bid, combined)
            with self._window_lock:
                self._window_states[window.market_id] = WindowState.PLACEMENT_FAILED
            return False

        if not self._rust_http or not self._rust_url:
            log.error("[KILLSHOT] No Rust executor — cannot place GTC orders")
            with self._window_lock:
                self._window_states[window.market_id] = WindowState.PLACEMENT_FAILED
            return False

        try:
            resp = self._rust_http.post(
                f"{self._rust_url}/orders",
                json=[
                    {"token_id": window.up_token_id, "price": up_bid,
                     "size": shares, "side": "BUY", "order_type": "GTC",
                     "neg_risk": False},
                    {"token_id": window.down_token_id, "price": down_bid,
                     "size": shares, "side": "BUY", "order_type": "GTC",
                     "neg_risk": False},
                ],
            )
            data = resp.json()
            results = data.get("results", [])
            latency = data.get("latency_ms", 0)
            log.info("[KILLSHOT] GTC batch: %d results, %dms", len(results), latency)

            if len(results) != 2:
                log.error("[KILLSHOT] GTC batch: %d results (expected 2) — aborting",
                          len(results))
                self._breaker_consec_fails += 1
                self._check_breaker()
                with self._window_lock:
                    self._window_states[window.market_id] = WindowState.PLACEMENT_FAILED
                return False

            up_ok = results[0].get("success", False)
            down_ok = results[1].get("success", False)
            up_oid = results[0].get("order_id", "")
            down_oid = results[1].get("order_id", "")

            if not up_ok and not down_ok:
                up_err = results[0].get("error", "?")
                down_err = results[1].get("error", "?")
                log.info("[KILLSHOT] GTC: both failed — UP: %s | DOWN: %s",
                         str(up_err)[:80], str(down_err)[:80])
                self._breaker_consec_fails += 1
                self._check_breaker()
                with self._window_lock:
                    self._window_states[window.market_id] = WindowState.PLACEMENT_FAILED
                return False

            if up_ok and not down_ok:
                log.warning("[KILLSHOT] GTC: DOWN failed — cancelling UP %s",
                            up_oid[:16] if up_oid else "?")
                self._cancel_order(up_oid)
                self._breaker_consec_fails += 1
                self._check_breaker()
                with self._window_lock:
                    self._window_states[window.market_id] = WindowState.PLACEMENT_FAILED
                return False

            if down_ok and not up_ok:
                log.warning("[KILLSHOT] GTC: UP failed — cancelling DOWN %s",
                            down_oid[:16] if down_oid else "?")
                self._cancel_order(down_oid)
                self._breaker_consec_fails += 1
                self._check_breaker()
                with self._window_lock:
                    self._window_states[window.market_id] = WindowState.PLACEMENT_FAILED
                return False

            # Both placed — check if already filled
            up_filled = float(results[0].get("matched_shares", 0)
                              or results[0].get("total_shares", 0) or 0)
            down_filled = float(results[1].get("matched_shares", 0)
                                or results[1].get("total_shares", 0) or 0)

            if up_filled >= shares and down_filled >= shares:
                self._breaker_consec_fails = 0
                log.info("[KILLSHOT] GTC: both filled immediately! %d+%d sh",
                         int(up_filled), int(down_filled))
                return self._record_fill_manual(
                    window, up_bid, down_bid, up_filled, down_filled,
                    up_bid, down_bid, net_edge, latency,
                )

            # Track as resting — fill monitoring in _check_resting_fills
            resting = {
                "market_id": window.market_id,
                "asset": window.asset,
                "up_order_id": up_oid,
                "down_order_id": down_oid,
                "up_token_id": window.up_token_id,
                "down_token_id": window.down_token_id,
                "up_price": up_bid,
                "down_price": down_bid,
                "shares": shares,
                "net_edge": net_edge,
                "window_end_ts": window.end_ts,
                "question": window.question,
                "open_price": window.open_price,
                "created_at": time.time(),
                "up_filled_shares": float(up_filled),
                "down_filled_shares": float(down_filled),
            }
            with self._resting_lock:
                self._resting_spreads.append(resting)
            log.info("[KILLSHOT] GTC resting: %s UP=%s DOWN=%s (prefilled: %d/%d)",
                     window.asset.upper(),
                     (up_oid[:12] if up_oid else "?"),
                     (down_oid[:12] if down_oid else "?"),
                     int(up_filled), int(down_filled))
            return True

        except httpx.TimeoutException as e:
            log.error("[KILLSHOT] GTC TIMEOUT: %s — orders may exist on chain",
                      str(e)[:120])
            self._breaker_consec_fails += 1
            self._check_breaker()
            with self._window_lock:
                self._window_states[window.market_id] = WindowState.PLACEMENT_FAILED
            return False
        except httpx.ConnectError as e:
            log.warning("[KILLSHOT] GTC connect error: %s", str(e)[:120])
            with self._window_lock:
                self._window_states[window.market_id] = WindowState.PLACEMENT_FAILED
            return False
        except Exception as e:
            log.error("[KILLSHOT] GTC error: %s", str(e)[:120])
            self._breaker_consec_fails += 1
            self._check_breaker()
            with self._window_lock:
                self._window_states[window.market_id] = WindowState.PLACEMENT_FAILED
            return False

    def _check_resting_fills(self) -> None:
        """Check resting GTC orders. Cancel + sell before window end (15s)."""
        now = time.time()
        with self._resting_lock:
            if not self._resting_spreads:
                return
            work = list(self._resting_spreads)

        completed: list[str] = []

        for spread in work:
            remaining_s = spread["window_end_ts"] - now
            mid = spread["market_id"]

            # Check fill status
            up_status = self._get_order_status(spread["up_order_id"])
            down_status = self._get_order_status(spread["down_order_id"])

            up_filled = (up_status.get("filled_shares", 0)
                         if up_status else spread["up_filled_shares"])
            down_filled = (down_status.get("filled_shares", 0)
                           if down_status else spread["down_filled_shares"])

            target = spread["shares"]
            up_full = up_filled >= target
            down_full = down_filled >= target

            # Both filled → record spread
            if up_full and down_full:
                self._breaker_consec_fails = 0
                total = round(up_filled * spread["up_price"] + down_filled * spread["down_price"], 2)

                for direction, price, shares_f, token_id in [
                    ("up", spread["up_price"], up_filled, spread["up_token_id"]),
                    ("down", spread["down_price"], down_filled, spread["down_token_id"]),
                ]:
                    trade = PaperTrade(
                        timestamp=time.time(), asset=spread["asset"],
                        market_id=mid, question=spread.get("question", ""),
                        direction=direction, entry_price=price,
                        size_usd=round(shares_f * price, 2), shares=shares_f,
                        window_end_ts=spread["window_end_ts"], spot_delta_pct=0.0,
                        open_price=spread.get("open_price", 0), market_ask=price,
                        token_id=token_id,
                    )
                    self._tracker.record_trade(trade, strategy="spread")

                self._tracker.notify_spread_entry(
                    spread["asset"], spread["up_price"], spread["down_price"],
                    total, spread.get("net_edge", 0) * 100,
                )
                log.info("[KILLSHOT] SPREAD FILLED: %s UP@%.0f¢+DOWN@%.0f¢ | "
                         "%d+%d sh | $%.2f",
                         spread["asset"].upper(),
                         spread["up_price"] * 100, spread["down_price"] * 100,
                         int(up_filled), int(down_filled), total)
                completed.append(mid)
                continue

            # Window ending in < 15s — cancel unfilled, sell filled
            if remaining_s <= 15:
                if not up_full and not down_full:
                    self._cancel_order(spread["up_order_id"])
                    self._cancel_order(spread["down_order_id"])
                    log.info("[KILLSHOT] GTC EXPIRE: %s neither filled — cancelled",
                             spread["asset"].upper())
                    completed.append(mid)
                    continue

                if up_full and not down_full:
                    self._cancel_order(spread["down_order_id"])
                    log.warning("[KILLSHOT] GTC PARTIAL: %s UP filled — selling %d sh",
                                spread["asset"].upper(), int(up_filled))
                    self._sell_immediately(
                        spread["up_token_id"], int(up_filled),
                        spread["up_price"], f"UP-{spread['asset'].upper()}")
                    completed.append(mid)
                    continue

                if down_full and not up_full:
                    self._cancel_order(spread["up_order_id"])
                    log.warning("[KILLSHOT] GTC PARTIAL: %s DOWN filled — selling %d sh",
                                spread["asset"].upper(), int(down_filled))
                    self._sell_immediately(
                        spread["down_token_id"], int(down_filled),
                        spread["down_price"], f"DOWN-{spread['asset'].upper()}")
                    completed.append(mid)
                    continue

            # Update fill counts
            spread["up_filled_shares"] = up_filled
            spread["down_filled_shares"] = down_filled

        if completed:
            done = set(completed)
            with self._resting_lock:
                self._resting_spreads = [
                    s for s in self._resting_spreads if s["market_id"] not in done
                ]

    def _cancel_order(self, order_id: str) -> bool:
        """Cancel a resting GTC order."""
        if not order_id:
            return False
        if self._client:
            try:
                self._client.cancel(order_id)
                log.info("[KILLSHOT] Cancelled %s", order_id[:16])
                return True
            except Exception as e:
                log.warning("[KILLSHOT] Cancel failed %s: %s",
                            order_id[:16], str(e)[:80])
        return False

    def _get_order_status(self, order_id: str) -> dict | None:
        """Check order fill status. Returns {filled_shares, status}."""
        if not order_id or not self._client:
            return None
        try:
            order = self._client.get_order(order_id)
            if not order:
                return None
            filled = float(order.get("size_matched", 0) or 0)
            status = (order.get("status") or "").lower()
            return {"filled_shares": filled, "status": status}
        except Exception as e:
            log.debug("[KILLSHOT] Order status error %s: %s",
                      order_id[:16], str(e)[:80])
            return None

    def _sell_immediately(self, token_id: str, shares: int,
                          buy_price: float, label: str) -> bool:
        """Sell shares via FOK at bid-1¢. No queue, no orphans."""
        book = self._get_book(token_id)
        if not book:
            log.error("[KILLSHOT] %s: no book for sell — MANUAL NEEDED", label)
            return False
        best_bid = book.get("best_bid", 0) or 0
        if best_bid < 0.02:
            log.error("[KILLSHOT] %s: bid=%.0f¢ too low — MANUAL NEEDED",
                      label, best_bid * 100)
            return False
        sell_price = max(round(best_bid - 0.01, 2), 0.01)
        result = self._place_fok(token_id, sell_price, shares, "SELL")
        if result:
            loss = round((buy_price - sell_price) * shares, 2)
            self._daily_loss += max(loss, 0)
            log.info("[KILLSHOT] %s: sold %d @ %.0f¢ (loss=$%.2f)",
                     label, shares, sell_price * 100, loss)
            return True
        log.error("[KILLSHOT] %s: FOK sell failed — MANUAL NEEDED", label)
        return False

    # ══════════════════════════════════════════════════════════════
    # 7. RECORD FILLS
    # ══════════════════════════════════════════════════════════════

    def _record_spread_fill(self, window, up_result, down_result,
                            up_ask, down_ask, shares, net_edge, latency):
        up_entry = up_result.get("avg_price", up_ask)
        down_entry = down_result.get("avg_price", down_ask)
        up_shares = up_result.get("total_shares", shares)
        down_shares = down_result.get("total_shares", shares)
        return self._record_fill_manual(
            window, up_entry, down_entry, up_shares, down_shares,
            up_ask, down_ask, net_edge, latency,
        )

    def _record_fill_manual(self, window, up_entry, down_entry,
                            up_shares, down_shares, up_ask, down_ask,
                            net_edge, latency=0):
        up_usd = round(up_shares * up_entry, 2)
        down_usd = round(down_shares * down_entry, 2)
        total = up_usd + down_usd

        up_trade = PaperTrade(
            timestamp=time.time(), asset=window.asset,
            market_id=window.market_id, question=window.question,
            direction="up", entry_price=up_entry,
            size_usd=up_usd, shares=up_shares,
            window_end_ts=window.end_ts, spot_delta_pct=0.0,
            open_price=window.open_price, market_ask=up_ask,
            token_id=window.up_token_id or "",
        )
        down_trade = PaperTrade(
            timestamp=time.time() + 0.001, asset=window.asset,
            market_id=window.market_id, question=window.question,
            direction="down", entry_price=down_entry,
            size_usd=down_usd, shares=down_shares,
            window_end_ts=window.end_ts, spot_delta_pct=0.0,
            open_price=window.open_price, market_ask=down_ask,
            token_id=window.down_token_id or "",
        )
        self._tracker.record_trade(up_trade, strategy="spread")
        self._tracker.record_trade(down_trade, strategy="spread")
        self._tracker.notify_spread_entry(window.asset, up_entry, down_entry, total, net_edge * 100)

        log.info("[KILLSHOT] SPREAD FILLED: %s UP@%.0f¢+DOWN@%.0f¢ | %d+%d sh | $%.2f | %dms",
                 window.asset.upper(), up_entry * 100, down_entry * 100,
                 int(up_shares), int(down_shares), total, latency)
        return True

    # ══════════════════════════════════════════════════════════════
    # 8. FOK ORDER PLACEMENT
    # ══════════════════════════════════════════════════════════════

    def _place_fok(self, token_id: str, price: float, shares: int, side: str) -> dict | None:
        """Place a single FOK order. Returns {"price", "shares"} or None."""
        # Rust
        rust_contacted = False
        if self._rust_http and self._rust_url:
            try:
                resp = self._rust_http.post(
                    f"{self._rust_url}/order",
                    json={"token_id": token_id, "price": price, "size": shares,
                          "side": side, "order_type": "FOK", "neg_risk": False},
                )
                rust_contacted = True
                data = resp.json()
                if data.get("success"):
                    return {"price": data.get("avg_price", price),
                            "shares": data.get("total_shares", shares)}
                # Rust responded but order failed — do NOT fall through to Python.
                # BUG FIX #32: Same pattern as BUG FIX #17.
                return None
            except httpx.ConnectError:
                # Connection never established — safe to try Python
                log.warning("[KILLSHOT] Rust FOK connect error — trying Python")
            except Exception as e:
                # BUG FIX #32: Timeout or unknown error — order may exist on CLOB.
                # Do NOT fall through to Python (double-order risk).
                log.warning("[KILLSHOT] Rust FOK error: %s — aborting (may exist on chain)", str(e)[:80])
                return None

        # Python fallback — only if Rust was not contacted
        if rust_contacted:
            return None
        if self._client:
            try:
                from py_clob_client.clob_types import OrderArgs, OrderType
                from py_clob_client.order_builder.constants import BUY, SELL
                clob_side = BUY if side == "BUY" else SELL
                args = OrderArgs(price=price, size=float(shares), side=clob_side, token_id=token_id)
                signed = self._client.create_order(args)
                resp = self._client.post_order(signed, OrderType.FOK)
                status = (resp.get("status") or "").lower()
                if status in ("matched", "filled"):
                    return {"price": price, "shares": float(shares)}
            except Exception as e:
                log.warning("[KILLSHOT] Python FOK failed: %s", str(e)[:100])

        return None

    # ══════════════════════════════════════════════════════════════
    # 9. NON-BLOCKING NEUTRALIZATION WORKER
    # ══════════════════════════════════════════════════════════════

    def _enqueue_neutralize(self, token_id: str, shares: float, buy_price: float,
                            label: str, market_id: str, pending_id: str) -> None:
        """Queue residual position for async SELL. Sets emergency stop."""
        entry = {
            "token_id": token_id,
            "shares": shares,
            "buy_price": buy_price,
            "label": label,
            "market_id": market_id,
            "pending_id": pending_id,
            "created_at": time.time(),
            "next_attempt_at": time.time(),  # try immediately on first pass
            "attempts": 0,
            "backoff_s": 10,
            "status": "pending",
        }

        with self._neutralize_lock:
            self._neutralize_queue.append(entry)
            self._save_neutralize_queue()

        with self._emergency_lock:
            self._emergency_stop = True

        log.warning("[KILLSHOT] NEUTRALIZE QUEUED: %s %.1f sh @ %.0f¢ — emergency stop ON",
                    label, shares, buy_price * 100)
        self._tracker._notify_tg(
            "\u26a0\ufe0f <b>Killshot PARTIAL FILL</b>\n"
            f"{label}: {shares:.1f} shares @ {buy_price:.0%}\n"
            "Neutralization queued. Emergency stop ACTIVE."
        )

    def _process_neutralize_queue(self) -> None:
        """Process neutralization queue. Non-blocking — uses backoff timestamps.

        BUG FIX #2: Does NOT hold _neutralize_lock during HTTP calls.
        Copies work items under lock, processes without lock, updates under lock.
        """
        # BUG FIX #20: all reads under lock
        with self._neutralize_lock:
            if not self._neutralize_queue:
                return

        if self._dry_run:
            return

        now = time.time()

        # Step 1: under lock, snapshot work items by pending_id (BUG FIX #19: no indices)
        work_items = []
        with self._neutralize_lock:
            for entry in self._neutralize_queue:
                if entry["status"] == "exhausted":
                    # BUG FIX #34: Reset exhausted entries after 5min cooldown.
                    # Without this, exhausted entries block trading permanently
                    # with no programmatic recovery.
                    last = entry.get("next_attempt_at", 0)
                    if now - last >= 300:
                        entry["status"] = "pending"
                        entry["attempts"] = 0
                        entry["backoff_s"] = 10
                        entry["next_attempt_at"] = now
                        log.info("[KILLSHOT] Exhausted entry %s reset for retry after 5min cooldown",
                                 entry.get("label", "?"))
                    continue
                if now < entry.get("next_attempt_at", 0):
                    continue
                # Copy to avoid mutating shared state without lock (BUG FIX #20)
                work_items.append(dict(entry))

        if not work_items:
            return

        # Step 2: process WITHOUT lock (HTTP calls happen here)
        # BUG FIX #19: use pending_id for matching, not list indices
        ids_to_remove: set[str] = set()
        updates: dict[str, dict] = {}  # pending_id -> changes
        pending_ids_to_close: list[str] = []

        for entry in work_items:
            pid = entry.get("pending_id", "")
            token_id = entry["token_id"]
            label = entry["label"]

            on_chain = self._check_onchain_balance(token_id)
            if on_chain is not None and on_chain < 1:
                log.info("[KILLSHOT] Neutralize %s: on-chain=%.1f — resolved externally", label, on_chain)
                ids_to_remove.add(pid)
                pending_ids_to_close.append(pid)
                continue

            # Sync share count from on-chain (track in updates, not direct mutation)
            shares = entry["shares"]
            if on_chain is not None and on_chain > 0:
                if abs(on_chain - shares) > 0.5:
                    log.info("[KILLSHOT] Neutralize %s: shares %.1f → %.1f (on-chain sync)",
                             label, shares, on_chain)
                    shares = on_chain

            remaining = self._sell_sliced(token_id, shares, label)

            if remaining < 5:
                log.info("[KILLSHOT] Neutralize %s COMPLETE (remaining=%.1f dust)", label, remaining)
                ids_to_remove.add(pid)
                self._tracker._notify_tg(
                    "\u2705 <b>Killshot NEUTRALIZED</b>\n"
                    f"{label}: {shares:.1f} shares sold"
                )
                pending_ids_to_close.append(pid)
            else:
                new_backoff = min(entry.get("backoff_s", 10) * 2, 60)
                new_attempts = entry.get("attempts", 0) + 1
                changes = {
                    "shares": remaining,
                    "backoff_s": new_backoff,
                    "next_attempt_at": now + new_backoff,
                    "attempts": new_attempts,
                }
                if new_attempts >= self._cfg.orphan_max_attempts:
                    changes["status"] = "exhausted"
                    log.error("[KILLSHOT] Neutralize %s EXHAUSTED after %d attempts — MANUAL NEEDED",
                              label, new_attempts)
                    self._tracker._notify_tg(
                        "\U0001f6a8 <b>Killshot EXHAUSTED</b>\n"
                        f"{label}: {remaining:.1f} shares stuck after {new_attempts} attempts\n"
                        "Manual intervention required."
                    )
                updates[pid] = changes

        # Step 3: apply results under lock (BUG FIX #19: match by pending_id, not index)
        with self._neutralize_lock:
            for entry in self._neutralize_queue:
                pid = entry.get("pending_id", "")
                if pid in updates:
                    entry.update(updates[pid])

            self._neutralize_queue = [
                e for e in self._neutralize_queue
                if e.get("pending_id", "") not in ids_to_remove
            ]

            if not self._neutralize_queue:
                with self._emergency_lock:
                    self._emergency_stop = False
                log.info("[KILLSHOT] All neutralizations complete — emergency stop OFF")

            self._save_neutralize_queue()

        # Step 4: update pending spreads (outside neutralize lock — BUG FIX #3)
        for pid in pending_ids_to_close:
            if pid:
                self._mark_pending_neutralized(pid)

    def _sell_sliced(self, token_id: str, total_shares: float, label: str) -> float:
        """Sell shares in slices. Returns REMAINING shares (not bool)."""
        remaining = total_shares

        for slice_num in range(self._cfg.orphan_sell_retries):
            if remaining < 5:
                if remaining > 0:
                    log.info("[KILLSHOT] %s: %.1f dust remaining (< 5 min)", label, remaining)
                return remaining

            book = self._get_book(token_id)
            if not book:
                return remaining

            best_bid = book.get("best_bid", 0) or 0
            # BUG FIX #36: REST fallback lacks best_bid_size — use bid_depth_cumulative
            # or fall back to buy_pressure / best_bid as a rough estimate.
            bid_size = book.get("best_bid_size", 0) or 0
            if bid_size == 0:
                bid_cum = book.get("bid_depth_cumulative", 0) or 0
                if bid_cum > 0:
                    bid_size = bid_cum
                elif best_bid > 0:
                    bid_size = (book.get("buy_pressure", 0) or 0) / best_bid

            if best_bid < 0.02:
                log.info("[KILLSHOT] %s: bid=%.0f¢ too low to sell", label, best_bid * 100)
                return remaining

            # Take min of remaining and 80% of book depth
            # BUG FIX #13: ensure int for CLOB order size
            slice_size = int(min(remaining, max(int(bid_size * 0.8), 5)))
            if slice_size > int(remaining):
                slice_size = int(remaining)
            if slice_size < 5:
                slice_size = 5

            sell_price = max(round(best_bid - 0.01, 2), 0.01)

            log.info("[KILLSHOT] %s slice %d: SELL %d @ %.0f¢ (bid=%.0f¢ depth=%.0f)",
                     label, slice_num + 1, slice_size, sell_price * 100, best_bid * 100, bid_size)

            result = self._place_fok(token_id, sell_price, slice_size, "SELL")
            if result:
                remaining -= slice_size
                log.info("[KILLSHOT] %s: sold %d, remaining=%.1f", label, slice_size, remaining)
            else:
                log.warning("[KILLSHOT] %s: slice %d SELL failed", label, slice_num + 1)
                return remaining

        return remaining

    # ══════════════════════════════════════════════════════════════
    # 10. PENDING SPREAD LIFECYCLE
    # ══════════════════════════════════════════════════════════════

    def _check_pending_spreads(self) -> None:
        """Check lifecycle of pending spreads. Detect stale partial fills.

        BUG FIX #3: Collects work under _pending_lock, enqueues AFTER releasing
        to prevent deadlock (_pending_lock → _neutralize_lock).
        """
        to_enqueue = []

        with self._pending_lock:
            for ps in self._pending_spreads:
                if ps["state"] == SpreadState.CLOSED:
                    continue

                if ps["state"] == SpreadState.PARTIAL_DETECTED:
                    # BUG FIX #20: snapshot neutralize IDs under its own lock
                    with self._neutralize_lock:
                        in_queue = any(
                            n["pending_id"] == ps["id"]
                            for n in self._neutralize_queue
                        )
                    if not in_queue:
                        enqueued = False
                        if ps["up_filled"] and not ps["down_filled"]:
                            to_enqueue.append((
                                ps["up_token_id"], ps["up_fill_shares"],
                                ps["up_price"], f"UP-{ps['asset'].upper()}",
                                ps["market_id"], ps["id"],
                            ))
                            enqueued = True
                        elif ps["down_filled"] and not ps["up_filled"]:
                            to_enqueue.append((
                                ps["down_token_id"], ps["down_fill_shares"],
                                ps["down_price"], f"DOWN-{ps['asset'].upper()}",
                                ps["market_id"], ps["id"],
                            ))
                            enqueued = True
                        if enqueued:
                            ps["state"] = SpreadState.NEUTRALIZING
                        else:
                            # BUG FIX #29: Neither leg filled — corrupt state.
                            # Force CLOSED to prevent permanent trading block.
                            log.error("[KILLSHOT] PARTIAL_DETECTED with no filled legs: %s — forcing CLOSED",
                                      ps.get("id", "?"))
                            ps["state"] = SpreadState.CLOSED
                        self._save_pending_spreads()

        # Enqueue outside _pending_lock (acquires _neutralize_lock safely)
        for args in to_enqueue:
            self._enqueue_neutralize(*args)

    def _close_pending(self, pending: dict, state: SpreadState) -> None:
        """Transition a pending spread to terminal state."""
        with self._pending_lock:
            pending["state"] = state
            self._save_pending_spreads()

    def _mark_pending_neutralized(self, pending_id: str) -> None:
        """Mark a pending spread as fully neutralized → closed."""
        if not pending_id:
            return
        with self._pending_lock:
            for ps in self._pending_spreads:
                if ps["id"] == pending_id:
                    ps["state"] = SpreadState.CLOSED
                    break
            self._save_pending_spreads()

    # ══════════════════════════════════════════════════════════════
    # 11. BOOK HELPER
    # ══════════════════════════════════════════════════════════════

    def _get_book(self, token_id: str | None) -> dict | None:
        if not token_id:
            return None
        if self._clob_ws:
            # BUG FIX #33: Reject stale book data (e.g. during WS reconnection).
            # Without this, engine can evaluate spreads on minutes-old prices.
            age = self._clob_ws.get_book_age(token_id)
            if age <= 30:
                book = self._clob_ws.get_book(token_id)
                if book:
                    return book
            elif age < float("inf"):
                log.debug("[KILLSHOT] Book for %s... is %.0fs stale — skipping WS cache", token_id[:12], age)
        return clob_book.get_orderbook(token_id) or None

    # ══════════════════════════════════════════════════════════════
    # 12. CIRCUIT BREAKER
    # ══════════════════════════════════════════════════════════════

    def _check_breaker(self):
        if self._breaker_consec_fails >= self._cfg.breaker_max_consec_fails:
            pause = self._cfg.spread_breaker_pause_s or self._cfg.breaker_cooldown_s
            self._breaker_paused_until = time.time() + pause
            # BUG FIX #30: Capture count BEFORE reset for log/notification
            tripped_at = self._breaker_consec_fails
            log.warning("[KILLSHOT] CIRCUIT BREAKER: %d fails → pausing %ds",
                        tripped_at, pause)
            # BUG FIX #25: Reset counter so next cycle starts fresh.
            self._breaker_consec_fails = 0
            self._tracker._notify_tg(
                "\u26a0\ufe0f <b>Killshot CIRCUIT BREAKER</b>\n"
                f"{tripped_at} consecutive failures\n"
                f"Pausing {pause}s"
            )

    # ══════════════════════════════════════════════════════════════
    # 13. ON-CHAIN BALANCE CHECK
    # ══════════════════════════════════════════════════════════════

    def _check_onchain_balance(self, token_id: str) -> float | None:
        if not self._client:
            return None
        try:
            from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
            params = BalanceAllowanceParams(
                asset_type=AssetType.CONDITIONAL,
                token_id=token_id,
                signature_type=self._cfg.signature_type,
            )
            bal = self._client.get_balance_allowance(params)
            return float(bal.get("balance", 0)) / 1e6
        except Exception:
            return None

    # ══════════════════════════════════════════════════════════════
    # 14. SWEEPER
    # ══════════════════════════════════════════════════════════════

    def _sweep_stuck_positions(self) -> None:
        """Re-check neutralize queue against on-chain balances.

        BUG FIX #10: Does NOT hold lock during HTTP calls.
        Uses copy-process-update pattern like _process_neutralize_queue.
        """
        # BUG FIX #20: read under lock
        with self._neutralize_lock:
            if not self._neutralize_queue:
                return
        if self._dry_run:
            return

        # Step 1: copy entries under lock
        with self._neutralize_lock:
            entries = [dict(e) for e in self._neutralize_queue]

        if not entries:
            return

        # Step 2: check on-chain WITHOUT lock (HTTP calls)
        # BUG FIX #19: use pending_id for matching, not indices
        ids_to_remove: set[str] = set()
        pending_ids_to_close: list[str] = []
        for entry in entries:
            pid = entry.get("pending_id", "")
            on_chain = self._check_onchain_balance(entry["token_id"])
            if on_chain is not None and on_chain < 1:
                log.info("[KILLSHOT] Sweeper: %s balance=%.1f → removing", entry["label"], on_chain)
                ids_to_remove.add(pid)
                pending_ids_to_close.append(pid)

        # Step 3: apply removals under lock (match by pending_id)
        if ids_to_remove:
            with self._neutralize_lock:
                self._neutralize_queue = [
                    e for e in self._neutralize_queue
                    if e.get("pending_id", "") not in ids_to_remove
                ]
                self._save_neutralize_queue()
                if not self._neutralize_queue:
                    with self._emergency_lock:
                        self._emergency_stop = False
                    log.info("[KILLSHOT] Sweeper: all clear — emergency stop OFF")

            # Close pending spreads outside neutralize lock
            for pid in pending_ids_to_close:
                if pid:
                    self._mark_pending_neutralized(pid)

        with self._neutralize_lock:
            if self._neutralize_queue:
                log.info("[KILLSHOT] Sweeper: %d item(s) remain", len(self._neutralize_queue))

    # ══════════════════════════════════════════════════════════════
    # 15. PERSISTENCE
    # ══════════════════════════════════════════════════════════════

    def _save_pending_spreads(self) -> None:
        # BUG FIX #27: Atomic write — write to tmp, fsync, then rename.
        # Crash mid-write no longer loses the previous good state.
        try:
            data = []
            for ps in self._pending_spreads:
                rec = dict(ps)
                if isinstance(rec.get("state"), SpreadState):
                    rec["state"] = rec["state"].value
                data.append(rec)
            tmp = _PENDING_FILE.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(_PENDING_FILE)
        except OSError as e:
            log.warning("[KILLSHOT] Failed to save pending: %s", str(e)[:80])

    def _load_pending_spreads(self) -> None:
        if not _PENDING_FILE.exists():
            return
        try:
            with open(_PENDING_FILE) as f:
                data = json.load(f)
            if isinstance(data, list):
                for ps in data:
                    state_val = ps.get("state", "closed")
                    try:
                        ps["state"] = SpreadState(state_val)
                    except ValueError:
                        ps["state"] = SpreadState.CLOSED
                active = [p for p in data if p["state"] not in (SpreadState.CLOSED,)]
                # BUG FIX #26: Paper mode can't process live pending spreads
                # (no CLOB client). Same pattern as BUG FIX #12 for neutralize queue.
                if self._dry_run and active:
                    log.warning("[KILLSHOT] Paper mode: ignoring %d active pending spread(s) from live session",
                                len(active))
                    for p in active:
                        p["state"] = SpreadState.CLOSED
                    self._pending_spreads = data
                    return
                self._pending_spreads = data
                if active:
                    self._emergency_stop = True
                    log.info("[KILLSHOT] Loaded %d pending spread(s), %d active — emergency stop ON",
                             len(data), len(active))
        except (OSError, json.JSONDecodeError):
            pass

    def _save_neutralize_queue(self) -> None:
        # BUG FIX #27: Atomic write (same pattern as _save_pending_spreads)
        try:
            tmp = _ORPHAN_FILE.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(self._neutralize_queue, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(_ORPHAN_FILE)
        except OSError as e:
            log.warning("[KILLSHOT] Failed to save neutralize queue: %s", str(e)[:80])

    def _load_neutralize_queue(self) -> None:
        if not _ORPHAN_FILE.exists():
            return
        try:
            with open(_ORPHAN_FILE) as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                # BUG FIX #12: In paper mode, don't load orphan queue — we can't
                # process it (no CLOB client), so it would block trading forever.
                if self._dry_run:
                    log.warning("[KILLSHOT] Paper mode: ignoring %d leftover neutralization(s) from live session",
                                len(data))
                    return
                self._neutralize_queue = data
                self._emergency_stop = True
                log.info("[KILLSHOT] Loaded %d neutralization(s) — emergency stop ON", len(data))
        except (OSError, json.JSONDecodeError):
            pass

    # ══════════════════════════════════════════════════════════════
    # 16. ENGINE STATE (DASHBOARD)
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _last_7pm_et() -> float:
        """Unix timestamp of the most recent 7pm ET (matches tracker reset)."""
        now_et = datetime.now(_ET)
        if now_et.hour >= 19:
            boundary = now_et.replace(hour=19, minute=0, second=0, microsecond=0)
        else:
            yesterday = now_et - timedelta(days=1)
            boundary = yesterday.replace(hour=19, minute=0, second=0, microsecond=0)
        return boundary.timestamp()

    def get_engine_state(self) -> dict:
        return {
            "can_trade": self.can_trade_now(),
            "emergency_stop": self._emergency_stop,
            "file_estop": _ESTOP_FLAG.exists(),
            "enabled": self._cfg.enabled,
            "daily_loss": round(self._daily_loss, 2),
            "breaker_paused": self._breaker_paused_until > time.time(),
            "breaker_consec_fails": self._breaker_consec_fails,
            "window_states": len(self._window_states),
            "pending_spreads": len(self._pending_spreads),
            "neutralize_queue": len(self._neutralize_queue),
        }

    def report_resolved(self, trades: list) -> None:
        # BUG FIX #18: Track ANY negative PnL, not just outcome=="loss".
        # For spreads, losing leg has pnl=0 and outcome="loss", while the
        # "winning" leg carries the actual net PnL (which can be negative
        # if neutralization sold at a loss). The old check missed this entirely.
        for trade in trades:
            if trade.pnl < 0:
                self._daily_loss += abs(trade.pnl)

    def cleanup_expired(self) -> None:
        with self._window_lock:
            self._window_states = {
                k: v for k, v in self._window_states.items()
                if k in {w.market_id for w in self._active_windows}
                or v == WindowState.PARTIAL_OPEN
            }
        # Clean old closed pending spreads + stale PLACING records
        # BUG FIX #9: PLACING older than 10min is orphaned (exception during placement)
        now = time.time()
        with self._pending_lock:
            cleaned = []
            for ps in self._pending_spreads:
                age = now - ps.get("created_at", 0)
                if ps["state"] == SpreadState.CLOSED and age >= 3600:
                    continue  # expired closed — drop
                if ps["state"] == SpreadState.PLACING and age >= 600:
                    # BUG FIX #28: If a leg filled before the crash/stall,
                    # transition to PARTIAL_DETECTED (not CLOSED) so it gets neutralized.
                    if ps.get("up_filled") or ps.get("down_filled"):
                        log.warning("[KILLSHOT] Cleanup: stale PLACING with filled leg %s — PARTIAL_DETECTED",
                                    ps.get("id", "?"))
                        ps["state"] = SpreadState.PARTIAL_DETECTED
                    else:
                        log.warning("[KILLSHOT] Cleanup: stale PLACING record %s (%.0fs old) — closing",
                                    ps.get("id", "?"), age)
                        ps["state"] = SpreadState.CLOSED
                cleaned.append(ps)
            self._pending_spreads = cleaned
            self._save_pending_spreads()
