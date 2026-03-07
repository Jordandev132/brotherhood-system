"""Paper trade tracker — logs trades and computes running P&L.

Resolution: checks CLOB book price for our token after window close.
If token bid > 0.50, we won (resolved to $1). If < 0.50, we lost ($0).
Daily PnL resets every day at 7pm ET.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("killshot.tracker")

_TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PAPER_FILE = DATA_DIR / "killshot_paper.jsonl"
STATUS_FILE = DATA_DIR / "killshot_status.json"


@dataclass
class PaperTrade:
    """A single paper trade record."""

    timestamp: float
    asset: str
    market_id: str
    question: str
    direction: str        # "up" or "down"
    entry_price: float    # simulated maker order price (e.g. 0.87)
    size_usd: float       # dollar amount committed
    shares: float         # size_usd / entry_price
    window_end_ts: float  # when this 5m window closes
    spot_delta_pct: float # spot price change % that triggered this trade
    open_price: float     # asset open price at window start
    market_bid: float = 0.0   # CLOB best bid at entry time
    market_ask: float = 0.0   # CLOB best ask at entry time
    token_id: str = ""        # CLOB token we bought (for on-chain resolution)
    strategy: str = "directional"  # "directional" (kill zone) or "momentum" (early entry)
    outcome: str = ""     # "win", "loss", or "expired" (empty while pending)
    pnl: float = 0.0
    resolved_at: float = 0.0


# 7pm ET — daily PnL resets at this time each day
_ET = ZoneInfo("America/New_York")
_DAILY_RESET_HOUR_ET = 19


def _last_7pm_et_ts() -> float:
    """Unix timestamp of the most recent 7pm ET (today or yesterday)."""
    now_et = datetime.now(_ET)
    if now_et.hour >= _DAILY_RESET_HOUR_ET:
        boundary = now_et.replace(hour=_DAILY_RESET_HOUR_ET, minute=0, second=0, microsecond=0)
    else:
        yesterday = now_et.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        boundary = yesterday.replace(hour=_DAILY_RESET_HOUR_ET, minute=0, second=0, microsecond=0)
    return boundary.timestamp()


class PaperTracker:
    """Tracks trades, resolves via CLOB book price, computes stats."""

    def __init__(self):
        self._pending: list[PaperTrade] = []
        self._inherited_ts: set[float] = set()  # timestamps of pre-restart trades
        self._session_pnl: float = 0.0
        self._session_trades: int = 0
        self._session_wins: int = 0
        self._daily_pnl: float = 0.0
        self._daily_trades: int = 0
        self._daily_wins: int = 0
        self._daily_reset_ts: float = 0.0  # last 7pm ET boundary we reset at
        self._load_pending()

    def _load_pending(self) -> None:
        """Reload unresolved trades from disk (handles bot restarts)."""
        if not PAPER_FILE.exists():
            return
        now = time.time()
        with open(PAPER_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if not d.get("outcome") and d.get("window_end_ts", 0) > now - 600:
                        trade = PaperTrade(
                            timestamp=d["timestamp"],
                            asset=d["asset"],
                            market_id=d["market_id"],
                            question=d.get("question", ""),
                            direction=d["direction"],
                            entry_price=d["entry_price"],
                            size_usd=d["size_usd"],
                            shares=d["shares"],
                            window_end_ts=d["window_end_ts"],
                            spot_delta_pct=d.get("spot_delta_pct", 0),
                            open_price=d["open_price"],
                            token_id=d.get("token_id", ""),
                            strategy=d.get("strategy", "directional"),
                        )
                        self._pending.append(trade)
                        self._inherited_ts.add(trade.timestamp)
                except Exception:
                    continue
        if self._pending:
            log.info("Loaded %d pending trades from disk (won't count in session stats)", len(self._pending))

    def _maybe_reset_daily(self) -> None:
        """Reset daily PnL stats when we've passed a new 7pm ET boundary."""
        boundary = _last_7pm_et_ts()
        if boundary > self._daily_reset_ts:
            self._daily_pnl = 0.0
            self._daily_trades = 0
            self._daily_wins = 0
            self._daily_reset_ts = boundary

    def record_trade(self, trade: PaperTrade, strategy: str = "directional") -> None:
        """Log a new trade."""
        trade.strategy = strategy
        self._pending.append(trade)
        # Spread legs are counted as 1 trade on resolve, not per-leg
        if strategy != "spread":
            self._session_trades += 1
        self._append_to_file(trade)
        strat_tag = f" [{strategy}]" if strategy != "directional" else ""
        log.info(
            "[KILLSHOT] Paper trade%s: %s %s @ %.0f¢ ($%.2f, %.1f shares) | delta=%.3f%%",
            strat_tag, trade.direction.upper(), trade.asset, trade.entry_price * 100,
            trade.size_usd, trade.shares, trade.spot_delta_pct * 100,
        )

    def resolve_trades(self, price_cache, clob_ws=None) -> list[PaperTrade]:
        """Check pending trades — resolve using CLOB book price (on-chain truth).

        After window closes, check our token's book price:
        - bid > 0.50 → we won (token resolving to $1)
        - bid < 0.50 → we lost (token resolving to $0)

        Spread trades are resolved as pairs: net PnL = winning_shares - (up_cost + down_cost).
        """
        from bot.snipe import clob_book

        now = time.time()
        resolved = []
        still_pending = []
        # Collect spread trades for paired resolution
        spread_pending: dict[str, list[PaperTrade]] = {}  # market_id -> [up, down]

        for trade in self._pending:
            # Grace period: wait 30s after window close for resolution to settle
            if now < trade.window_end_ts + 30:
                still_pending.append(trade)
                continue

            # Expire trades older than 10 minutes past close
            if now > trade.window_end_ts + 600:
                trade.outcome = "expired"
                trade.resolved_at = now
                resolved.append(trade)
                self._update_in_file(trade)
                log.warning(
                    "[KILLSHOT] Expired: %s %s (missed resolution window)",
                    trade.direction, trade.asset,
                )
                continue

            # ── Spread trades: collect pairs first, resolve together ──
            if trade.strategy == "spread":
                key = trade.market_id
                if key not in spread_pending:
                    spread_pending[key] = []
                spread_pending[key].append(trade)
                continue

            # ── Non-spread (directional/momentum): resolve individually ──
            won = self._determine_outcome(trade, clob_ws, clob_book, price_cache)
            if won is None:
                still_pending.append(trade)
                continue

            if won:
                trade.outcome = "win"
                trade.pnl = round(trade.shares * (1.0 - trade.entry_price), 4)
            else:
                trade.outcome = "loss"
                trade.pnl = round(-trade.size_usd, 4)

            trade.resolved_at = now
            resolved.append(trade)
            self._update_in_file(trade)
            self._record_stats(trade)

        # ── Resolve spread pairs ──
        for market_id, trades in spread_pending.items():
            if len(trades) < 2:
                # Incomplete pair — keep pending
                still_pending.extend(trades)
                continue

            # Find up and down legs
            up_leg = next((t for t in trades if t.direction == "up"), None)
            down_leg = next((t for t in trades if t.direction == "down"), None)
            if not up_leg or not down_leg:
                still_pending.extend(trades)
                continue

            # Determine which leg won (token resolving to $1)
            up_won = self._determine_outcome(up_leg, clob_ws, clob_book, price_cache)
            if up_won is None:
                still_pending.extend(trades)
                continue

            # Spread PnL: winner pays $1/share, cost = up_cost + down_cost + fees
            up_cost = up_leg.shares * up_leg.entry_price
            down_cost = down_leg.shares * down_leg.entry_price

            if up_won:
                # UP token → $1, DOWN token → $0
                revenue = up_leg.shares * 1.0
                winning_leg, losing_leg = up_leg, down_leg
            else:
                # DOWN token → $1, UP token → $0
                revenue = down_leg.shares * 1.0
                winning_leg, losing_leg = down_leg, up_leg

            # CLOB fees: 2% * min(price, 1-price) per leg per share
            up_fee = 0.02 * min(up_leg.entry_price, 1.0 - up_leg.entry_price) * up_leg.shares
            down_fee = 0.02 * min(down_leg.entry_price, 1.0 - down_leg.entry_price) * down_leg.shares
            net_pnl = round(revenue - up_cost - down_cost - up_fee - down_fee, 4)

            # Mark both legs resolved — split PnL evenly for bookkeeping
            for leg in (up_leg, down_leg):
                leg.resolved_at = now
                if leg is winning_leg:
                    leg.outcome = "win"
                    leg.pnl = round(net_pnl, 4)  # Full spread PnL on winning leg
                else:
                    leg.outcome = "loss"
                    leg.pnl = 0.0  # Zero on losing leg (PnL is on winner)
                self._update_in_file(leg)
                resolved.append(leg)

            # Record stats once for the pair
            inherited = up_leg.timestamp in self._inherited_ts
            if not inherited:
                self._session_trades += 1  # Count as 1 spread trade
                self._session_pnl += net_pnl
                self._maybe_reset_daily()
                self._daily_trades += 1
                self._daily_pnl += net_pnl
                if net_pnl > 0:
                    self._session_wins += 1
                    self._daily_wins += 1

            wr = (self._session_wins / max(self._session_trades, 1)) * 100
            daily_wr = (self._daily_wins / max(self._daily_trades, 1)) * 100
            tag = " [inherited]" if inherited else ""
            sign = "+" if net_pnl >= 0 else ""
            log.info(
                "[KILLSHOT] SPREAD %s: %s | UP@%.0f¢ + DOWN@%.0f¢ → net %s$%.2f | "
                "Session: $%.2f (WR %.0f%%)%s",
                "WIN" if net_pnl > 0 else "LOSS",
                up_leg.asset.upper(), up_leg.entry_price * 100,
                down_leg.entry_price * 100, sign, net_pnl,
                self._session_pnl, wr, tag,
            )
            daily_sign = "+" if self._daily_pnl >= 0 else ""
            emoji = "\u2705" if net_pnl > 0 else "\u274c"
            self._notify_tg(
                f"{emoji} <b>Killshot [SPR] {'WIN' if net_pnl > 0 else 'LOSS'}</b>\n"
                f"{up_leg.asset.upper()} UP@{up_leg.entry_price:.0%} + DOWN@{down_leg.entry_price:.0%}\n"
                f"Net P&L: <b>{sign}${net_pnl:.2f}</b>\n"
                f"Session: {'+' if self._session_pnl >= 0 else ''}${self._session_pnl:.2f} | WR {wr:.0f}% ({self._session_trades} trades)\n"
                f"Daily: {daily_sign}${self._daily_pnl:.2f} | WR {daily_wr:.0f}% ({self._daily_trades} trades)"
            )

        self._pending = still_pending
        return resolved

    def _determine_outcome(self, trade, clob_ws, clob_book, price_cache):
        """Determine if a trade's token won. Returns True/False/None (can't determine yet)."""
        won = None
        if trade.token_id:
            book = None
            if clob_ws:
                book = clob_ws.get_book(trade.token_id)
            if book is None:
                book = clob_book.get_orderbook(trade.token_id)
            if book:
                bid = book.get("best_bid", 0) or 0
                ask = book.get("best_ask", 0) or 0
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else bid or ask
                if mid > 0.50:
                    won = True
                elif mid < 0.50:
                    won = False

        if won is None:
            current_price = price_cache.get_resolution_price(trade.asset)
            if current_price is None:
                return None
            went_up = current_price > trade.open_price
            won = (trade.direction == "up" and went_up) or \
                  (trade.direction == "down" and not went_up)

        return won

    def _record_stats(self, trade):
        """Record stats for a single non-spread trade."""
        inherited = trade.timestamp in self._inherited_ts
        if not inherited:
            if trade.outcome == "win":
                self._session_wins += 1
            self._session_pnl += trade.pnl
            self._maybe_reset_daily()
            self._daily_trades += 1
            if trade.outcome == "win":
                self._daily_wins += 1
            self._daily_pnl += trade.pnl

        wr = (self._session_wins / max(self._session_trades, 1)) * 100
        daily_wr = (self._daily_wins / max(self._daily_trades, 1)) * 100
        tag = " [inherited]" if inherited else ""
        log.info(
            "[KILLSHOT] %s: %s %s | P&L $%.2f | Session: $%.2f (WR %.0f%%)%s",
            trade.outcome.upper(), trade.direction.upper(), trade.asset,
            trade.pnl, self._session_pnl, wr, tag,
        )
        emoji = "\u2705" if trade.outcome == "win" else "\u274c"
        sign = "+" if trade.pnl >= 0 else ""
        strat_label = {"momentum": "MOM", "spread": "SPR", "directional": "KZ"}.get(trade.strategy, "KZ")
        daily_sign = "+" if self._daily_pnl >= 0 else ""
        # BUG FIX #38: Session PnL sign was using `sign` (derived from trade.pnl),
        # not from self._session_pnl. If trade lost but session is positive overall,
        # the "+" prefix was missing from the session line.
        session_sign = "+" if self._session_pnl >= 0 else ""
        self._notify_tg(
            f"{emoji} <b>Killshot [{strat_label}] {trade.outcome.upper()}</b>\n"
            f"{trade.direction.upper()} {trade.asset.upper()} @ {trade.entry_price:.0%}\n"
            f"P&L: <b>{sign}${trade.pnl:.2f}</b>\n"
            f"Session: {session_sign}${self._session_pnl:.2f} | WR {wr:.0f}% ({self._session_trades} trades)\n"
            f"Daily: {daily_sign}${self._daily_pnl:.2f} | WR {daily_wr:.0f}% ({self._daily_trades} trades)"
        )

    @staticmethod
    def _notify_tg(text: str) -> None:
        if not _TG_TOKEN or not _TG_CHAT:
            return
        try:
            import requests
            requests.post(
                f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
                json={"chat_id": _TG_CHAT, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception:
            pass

    def notify_spread_entry(
        self,
        asset: str,
        up_ask: float,
        down_ask: float,
        total_usd: float,
        guaranteed_profit_pct: float,
    ) -> None:
        """Send Telegram notification when a spread trade is entered (both legs)."""
        combined_cent = (up_ask + down_ask) * 100
        self._notify_tg(
            "\u2696\ufe0f <b>Killshot [SPR] ENTRY</b>\n"
            f"{asset.upper()} UP @ {up_ask:.0%} + DOWN @ {down_ask:.0%} = {combined_cent:.0f}\u00a2\n"
            f"Size: <b>${total_usd:.2f}</b> | Guaranteed: <b>{guaranteed_profit_pct:.1f}\u00a2/$</b>"
        )

    # ── File I/O ────────────────────────────────────────────────

    def _append_to_file(self, trade: PaperTrade) -> None:
        with open(PAPER_FILE, "a") as f:
            f.write(json.dumps(asdict(trade)) + "\n")

    def _update_in_file(self, trade: PaperTrade) -> None:
        """Rewrite the resolved trade's line in the JSONL file."""
        if not PAPER_FILE.exists():
            return
        lines = []
        updated = False
        with open(PAPER_FILE) as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    d = json.loads(stripped)
                    if (d.get("market_id") == trade.market_id
                            and d.get("timestamp") == trade.timestamp
                            and not updated):
                        lines.append(json.dumps(asdict(trade)))
                        updated = True
                    else:
                        lines.append(stripped)
                except Exception:
                    lines.append(stripped)
        if not updated:
            lines.append(json.dumps(asdict(trade)))
        tmp = PAPER_FILE.with_suffix(".jsonl.tmp")
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        tmp.replace(PAPER_FILE)

    # ── Stats & Dashboard ───────────────────────────────────────

    def get_stats(self) -> dict:
        """Dashboard-friendly statistics with per-strategy breakdown."""
        all_trades = self._load_all_trades()
        resolved = [t for t in all_trades if t.get("outcome") in ("win", "loss")]
        wins = sum(1 for t in resolved if t["outcome"] == "win")
        total_pnl = sum(t.get("pnl", 0) for t in resolved)
        avg_entry = 0.0
        if all_trades:
            avg_entry = sum(t.get("entry_price", 0) for t in all_trades) / len(all_trades)

        # Per-strategy breakdown
        strat_stats = {}
        for strat in ("directional", "momentum", "spread"):
            s_resolved = [t for t in resolved if t.get("strategy", "directional") == strat]
            s_wins = sum(1 for t in s_resolved if t["outcome"] == "win")
            s_pnl = sum(t.get("pnl", 0) for t in s_resolved)
            s_total = sum(1 for t in all_trades if t.get("strategy", "directional") == strat)
            strat_stats[strat] = {
                "trades": s_total,
                "resolved": len(s_resolved),
                "wins": s_wins,
                "losses": len(s_resolved) - s_wins,
                "win_rate": round(s_wins / len(s_resolved) * 100, 1) if s_resolved else 0,
                "pnl": round(s_pnl, 2),
            }

        self._maybe_reset_daily()
        return {
            "total_trades": len(all_trades),
            "resolved": len(resolved),
            "pending": len(self._pending),
            "wins": wins,
            "losses": len(resolved) - wins,
            "win_rate": round(wins / len(resolved) * 100, 1) if resolved else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_entry_price": round(avg_entry, 3),
            "session_pnl": round(self._session_pnl, 2),
            "session_trades": self._session_trades,
            "session_wins": self._session_wins,
            "daily_pnl": round(self._daily_pnl, 2),
            "daily_trades": self._daily_trades,
            "daily_wins": self._daily_wins,
            "daily_loss": round(abs(min(self._session_pnl, 0)), 2),
            "by_strategy": strat_stats,
        }

    def _load_all_trades(self) -> list[dict]:
        if not PAPER_FILE.exists():
            return []
        trades = []
        with open(PAPER_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(json.loads(line))
                except Exception:
                    continue
        return trades

    def get_recent_trades(self, limit: int = 50) -> list[dict]:
        """Return recent trades for dashboard display."""
        return self._load_all_trades()[-limit:]

    def write_status(self, engine_state: dict | None = None) -> None:
        """Persist status JSON for dashboard consumption."""
        status = self.get_stats()
        status["updated_at"] = time.time()
        status["pending_details"] = [
            {
                "asset": t.asset,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "size_usd": t.size_usd,
                "window_end_ts": t.window_end_ts,
                "remaining_s": max(0, round(t.window_end_ts - time.time())),
            }
            for t in self._pending
        ]
        if engine_state:
            status["engine"] = engine_state
        tmp = STATUS_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(status, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.rename(STATUS_FILE)
