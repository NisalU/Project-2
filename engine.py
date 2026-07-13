"""Confluence engine: runs all strategies, combines weighted votes into a
composite score (-100..+100) and fires LONG/SHORT signals above threshold.
"""
import json
import os
import threading
import time
import traceback

import config
import data_feed
from strategies import (auction, ema_trend, fibonacci, fundamentals, liquidity,
                        orderflow, patterns, smc, support_resistance, trendlines)
from strategies.helpers import atr

SIGNALS_FILE = os.path.join(os.path.dirname(__file__), "signals.json")

STRATEGIES = {
    "ema_trend": ("EMA 7/25/99", lambda c, f: ema_trend.analyze(c)),
    "support_resistance": ("Support / Resistance", lambda c, f: support_resistance.analyze(c)),
    "trendlines": ("Trendlines", lambda c, f: trendlines.analyze(c)),
    "patterns": ("Chart Patterns", lambda c, f: patterns.analyze(c)),
    "fibonacci": ("Fibonacci", lambda c, f: fibonacci.analyze(c)),
    "smc": ("Smart Money Concepts", lambda c, f: smc.analyze(c)),
    "liquidity_sweep": ("Liquidity Sweeps", lambda c, f: liquidity.analyze(c)),
    "orderflow_cvd": ("Orderflow / CVD", lambda c, f: orderflow.analyze(c)),
    "auction_market": ("Auction Market", lambda c, f: auction.analyze(c)),
    "fundamentals": ("Fundamentals", lambda c, f: fundamentals.analyze(c, f)),
}


class Engine:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}          # (symbol, interval) -> analysis dict
        self.symbol = config.DEFAULT_SYMBOL
        self.interval = config.DEFAULT_INTERVAL
        self.signals = self._load_signals()
        self._last_signal_key = {}  # avoid duplicate consecutive signals

    # ---------- persistence ----------
    def _load_signals(self):
        try:
            with open(SIGNALS_FILE) as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return []

    def _save_signals(self):
        try:
            with open(SIGNALS_FILE, "w") as fh:
                json.dump(self.signals[-config.MAX_SIGNAL_HISTORY:], fh)
        except Exception:  # noqa: BLE001
            pass

    # ---------- analysis ----------
    def analyze(self, symbol, interval):
        candles = data_feed.get_klines(symbol, interval)
        futures_stats = data_feed.get_futures_stats(symbol)
        ticker = None
        try:
            ticker = data_feed.get_ticker(symbol)
        except data_feed.DataError:
            pass

        breakdown = []
        overlays = {}
        composite = 0.0
        for key, (label, fn) in STRATEGIES.items():
            weight = config.WEIGHTS.get(key, 0)
            try:
                res = fn(candles, futures_stats)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                res = {"score": 0, "reasons": ["strategy error"], "overlays": {}}
            contribution = res["score"] * weight
            composite += contribution
            breakdown.append({
                "key": key, "label": label, "weight": weight,
                "score": round(res["score"], 3),
                "contribution": round(contribution, 2),
                "reasons": res["reasons"],
            })
            overlays.update(res.get("overlays", {}))

        composite = max(-100.0, min(100.0, composite))
        direction = "LONG" if composite >= config.SIGNAL_THRESHOLD else \
                    "SHORT" if composite <= -config.SIGNAL_THRESHOLD else "NEUTRAL"
        strength = "STRONG" if abs(composite) >= config.STRONG_THRESHOLD else \
                   "MODERATE" if direction != "NEUTRAL" else ""

        price = candles[-1]["close"]
        a = atr(candles) or price * 0.005
        plan = None
        if direction != "NEUTRAL":
            sign = 1 if direction == "LONG" else -1
            plan = {
                "entry": price,
                "stop": price - sign * a * 1.5,
                "tp1": price + sign * a * 1.5,
                "tp2": price + sign * a * 3.0,
            }

        analysis = {
            "symbol": symbol,
            "interval": interval,
            "updated": int(time.time()),
            "price": price,
            "ticker": ticker,
            "composite": round(composite, 1),
            "direction": direction,
            "strength": strength,
            "threshold": config.SIGNAL_THRESHOLD,
            "plan": plan,
            "breakdown": breakdown,
            "overlays": overlays,
            "candles": candles,
        }

        # Record signal event on new non-neutral direction for this market
        mk = f"{symbol}:{interval}"
        if direction != "NEUTRAL" and self._last_signal_key.get(mk) != direction:
            top = sorted(breakdown, key=lambda b: -abs(b["contribution"]))[:4]
            self.signals.append({
                "time": int(time.time()),
                "symbol": symbol, "interval": interval,
                "direction": direction, "strength": strength,
                "score": round(composite, 1), "price": price,
                "plan": plan,
                "reasons": [r for b in top for r in b["reasons"][:1] if r],
            })
            self.signals = self.signals[-config.MAX_SIGNAL_HISTORY:]
            self._save_signals()
        self._last_signal_key[mk] = direction

        with self._lock:
            self._state[mk] = analysis
        return analysis

    def get_state(self, symbol, interval):
        mk = f"{symbol}:{interval}"
        with self._lock:
            cached = self._state.get(mk)
        # Serve cache if fresh enough, else analyze on demand
        if cached and time.time() - cached["updated"] < config.REFRESH_SECONDS * 2:
            return cached
        return self.analyze(symbol, interval)

    # ---------- background loop ----------
    def start(self):
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while True:
            try:
                self.analyze(self.symbol, self.interval)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            time.sleep(config.REFRESH_SECONDS)


engine = Engine()
