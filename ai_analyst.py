"""Groq AI analyst — live 1h chart monitoring with order-flow-first entries.

Feeds the confluence engine's full 1h analysis (all 10 strategies, with the
orderflow/CVD strategy highlighted) to a Groq-hosted LLM and asks for a
structured trade call: LONG / SHORT / WAIT with exact entry, stop, targets
and reasoning grounded in order flow.

Pure Python — uses `requests` only, so it runs on Termux.
"""
import json
import os
import threading
import time
import traceback

import requests

import config
from engine import engine

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Tried in order; first model that responds is cached for the session.
GROQ_MODELS = [
    os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "llama-3.1-8b-instant",
]

SYSTEM_PROMPT = """You are an elite crypto futures trader specialising in ORDER FLOW analysis \
(delta, CVD, absorption, liquidity sweeps). You are given a full 1-hour-chart confluence \
analysis produced by an algorithmic engine. Your PRIMARY strategy is order flow: weight the \
Orderflow/CVD and Liquidity Sweep readings most heavily, then use Smart Money Concepts, \
support/resistance and the volume profile (POC/VAH/VAL) to pick the best exact entry price. \
Only call LONG or SHORT when order flow genuinely supports it; otherwise answer WAIT. \
Entries must be realistic limit prices near current price or a nearby untested level — never \
more than ~2% away. Stop must sit beyond the invalidating structure. \
Respond ONLY with a JSON object with these exact keys:
{"signal": "LONG"|"SHORT"|"WAIT",
 "confidence": <int 0-100>,
 "entry": <number|null>,
 "stop": <number|null>,
 "tp1": <number|null>,
 "tp2": <number|null>,
 "risk_reward": <number|null>,
 "orderflow_read": "<one sentence: what delta/CVD/absorption is saying>",
 "reasoning": "<2-3 sentences: why this call, which levels matter>",
 "invalidation": "<one sentence: what would flip or cancel this idea>"}
For WAIT, entry/stop/tp1/tp2/risk_reward may be null. Numbers must be plain (no strings)."""


def _get_api_key():
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key
    # fall back to a local .env-style file (handy on Termux)
    base = os.path.dirname(__file__)
    for name in (".env", ".env.local", ".env.development.local"):
        try:
            with open(os.path.join(base, name)) as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("GROQ_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _fnum(x, digits=6):
    return round(float(x), digits)


def _compact_market(analysis):
    """Shrink the engine's analysis dict into a compact prompt payload."""
    candles = analysis["candles"]
    ov = analysis.get("overlays", {})

    recent = [
        {
            "t": c["time"], "o": _fnum(c["open"]), "h": _fnum(c["high"]),
            "l": _fnum(c["low"]), "c": _fnum(c["close"]),
            "vol": _fnum(c["volume"], 2), "delta": _fnum(c["delta"], 2),
        }
        for c in candles[-24:]
    ]

    cvd = ov.get("cvd") or []
    cvd_tail = [_fnum(p["value"], 2) for p in cvd[-24:]]

    strategies = [
        {
            "name": b["label"], "weight": b["weight"], "score": b["score"],
            "contribution": b["contribution"], "reasons": b["reasons"][:2],
        }
        for b in analysis["breakdown"]
    ]

    levels = {}
    if ov.get("support"):
        levels["support"] = [_fnum(lv["price"]) for lv in ov["support"][:4]]
    if ov.get("resistance"):
        levels["resistance"] = [_fnum(lv["price"]) for lv in ov["resistance"][:4]]
    if ov.get("volume_profile"):
        vp = ov["volume_profile"]
        levels["poc"] = _fnum(vp["poc"])
        levels["vah"] = _fnum(vp["vah"])
        levels["val"] = _fnum(vp["val"])
    if ov.get("order_blocks"):
        levels["order_blocks"] = [
            {"type": ob["type"], "top": _fnum(ob["top"]), "bottom": _fnum(ob["bottom"])}
            for ob in ov["order_blocks"][:3]
        ]
    if ov.get("fvgs"):
        levels["fvg_mids"] = [
            {"type": f["type"], "mid": _fnum(f["mid"])} for f in ov["fvgs"][:3]
        ]

    fundamentals = ov.get("fundamentals")

    return {
        "symbol": analysis["symbol"],
        "chart": "1h",
        "price": _fnum(analysis["price"]),
        "change_24h_pct": (analysis.get("ticker") or {}).get("change_pct"),
        "engine_composite_score": analysis["composite"],
        "engine_direction": analysis["direction"],
        "strategies": strategies,
        "orderflow_divergence": ov.get("divergence"),
        "cvd_last_24": cvd_tail,
        "key_levels": levels,
        "futures_fundamentals": fundamentals,
        "recent_1h_candles": recent,
    }


class AIAnalyst:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = {}          # symbol -> ai result dict
        self._model = None        # first working model, cached
        self.enabled = bool(_get_api_key())
        self.last_error = None

    def get_cached(self, symbol):
        with self._lock:
            return self._cache.get(symbol)

    # ---------------- Groq call ----------------
    def _call_groq(self, payload_text):
        key = _get_api_key()
        if not key:
            raise RuntimeError("GROQ_API_KEY not set")
        models = [self._model] if self._model else []
        models += [m for m in GROQ_MODELS if m and m not in models]
        last_exc = None
        for model in models:
            try:
                resp = requests.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "temperature": 0.2,
                        "max_tokens": 600,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": payload_text},
                        ],
                    },
                    timeout=45,
                )
                if resp.status_code == 200:
                    self._model = model
                    body = resp.json()
                    return model, body["choices"][0]["message"]["content"]
                # model gone / not allowed -> try next model
                if resp.status_code in (400, 404) and "model" in resp.text.lower():
                    last_exc = RuntimeError(f"{model}: {resp.status_code} {resp.text[:120]}")
                    continue
                if resp.status_code == 429:
                    raise RuntimeError(f"Groq rate limited: {resp.text[:120]}")
                raise RuntimeError(f"Groq HTTP {resp.status_code}: {resp.text[:160]}")
            except requests.RequestException as e:
                last_exc = e
                continue
        raise RuntimeError(f"all Groq models failed: {last_exc}")

    # ---------------- public API ----------------
    def analyze(self, symbol):
        """Run AI analysis on the 1h chart for `symbol`. Blocking (call in thread)."""
        analysis = engine.get_state(symbol, config.AI_INTERVAL)
        market = _compact_market(analysis)
        user_text = (
            "Analyze this live 1h market data and give your best order-flow-based "
            "trade call as JSON:\n" + json.dumps(market, separators=(",", ":"))
        )
        model, raw = self._call_groq(user_text)
        try:
            out = json.loads(raw)
        except ValueError:
            raise RuntimeError(f"Groq returned non-JSON: {raw[:160]}")

        signal = str(out.get("signal", "WAIT")).upper()
        if signal not in ("LONG", "SHORT", "WAIT"):
            signal = "WAIT"

        def num(k):
            v = out.get(k)
            try:
                return round(float(v), 8) if v is not None else None
            except (TypeError, ValueError):
                return None

        result = {
            "symbol": symbol,
            "interval": config.AI_INTERVAL,
            "updated": int(time.time()),
            "price": analysis["price"],
            "engine_score": analysis["composite"],
            "model": model,
            "signal": signal,
            "confidence": max(0, min(100, int(out.get("confidence") or 0))),
            "entry": num("entry"),
            "stop": num("stop"),
            "tp1": num("tp1"),
            "tp2": num("tp2"),
            "risk_reward": num("risk_reward"),
            "orderflow_read": str(out.get("orderflow_read") or "")[:300],
            "reasoning": str(out.get("reasoning") or "")[:600],
            "invalidation": str(out.get("invalidation") or "")[:300],
        }
        with self._lock:
            self._cache[symbol] = result
        self.last_error = None
        return result

    def analyze_safe(self, symbol):
        """Like analyze() but never raises; returns cached/error placeholder."""
        try:
            return self.analyze(symbol)
        except Exception as e:  # noqa: BLE001
            self.last_error = str(e)
            traceback.print_exc()
            cached = self.get_cached(symbol)
            if cached:
                return cached
            return {
                "symbol": symbol,
                "interval": config.AI_INTERVAL,
                "updated": int(time.time()),
                "error": str(e)[:200],
            }


ai_analyst = AIAnalyst()
