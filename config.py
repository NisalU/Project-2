"""Configuration for the AI Trading Signal Bot."""

# ---- Server ----
HOST = "0.0.0.0"   # listen on all interfaces so other devices on LAN can open the dashboard
PORT = 8000

# ---- Market data ----
DEFAULT_SYMBOL = "BTCUSDT"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
DEFAULT_INTERVAL = "15m"
INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
KLINE_LIMIT = 300           # candles fetched per analysis

# Binance REST endpoints, tried in order (first that works is cached).
# data-api.binance.vision is Binance's public market-data mirror and
# usually works even where api.binance.com is geo-restricted.
SPOT_ENDPOINTS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://data-api.binance.vision",
]
FUTURES_ENDPOINTS = [
    "https://fapi.binance.com",
]

REFRESH_SECONDS = 20        # background analysis loop interval

# ---- Confluence engine ----
# Weight of each strategy in the composite score (must not exceed 100 total).
WEIGHTS = {
    "ema_trend": 12,
    "support_resistance": 12,
    "trendlines": 8,
    "patterns": 8,
    "fibonacci": 8,
    "smc": 14,
    "liquidity_sweep": 10,
    "orderflow_cvd": 14,
    "auction_market": 8,
    "fundamentals": 6,
}

SIGNAL_THRESHOLD = 45       # |composite| >= threshold fires a LONG/SHORT signal
STRONG_THRESHOLD = 65       # strong signal label
MAX_SIGNAL_HISTORY = 200    # kept in memory / persisted to signals.json
