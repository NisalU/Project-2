# AI Trading Signal Bot (Termux + Web Dashboard)

A pure-Python crypto trading signal bot that analyzes Binance market data with
10 strategies and serves a live charting dashboard on your phone's local IP.

No numpy / pandas — only `flask` and `requests`, so it installs cleanly on Termux.

## Strategies (confluence scored)

| Strategy | What it detects |
| --- | --- |
| EMA 7/25/99 | Trend stack alignment, fresh 7/25 crosses |
| Support / Resistance | Clustered swing levels, bounces, breakouts |
| Trendlines | Regression-fit trendlines, bounces and breaks |
| Chart Patterns | Engulfing, pin bars, double top/bottom, head & shoulders |
| Fibonacci | Retracement of dominant swing (0.5 / 0.618 golden zone) |
| Smart Money Concepts | BOS / CHoCH, order blocks, fair value gaps |
| Liquidity Sweeps | Stop hunts through equal highs/lows that reverse |
| Orderflow / CVD | Delta pressure, CVD divergence, absorption |
| Auction Market | Volume profile POC, value area acceptance/rejection |
| Fundamentals | Funding rate, open interest, long/short ratio |

Each strategy votes -1..+1 and is weighted (see `config.py`). A LONG/SHORT
signal fires when the composite score crosses the threshold (default 45/100),
together with an ATR-based trade plan (entry / stop / TP1 / TP2).

## Install on Termux

```bash
pkg update && pkg install python git
git clone <your-repo-url> signal-bot && cd signal-bot
pip install -r requirements.txt
python server.py
```

The console prints your local network URL, e.g.:

```
  Local:   http://127.0.0.1:8000
  Network: http://192.168.1.23:8000
```

Open the Network URL from any browser on the same Wi-Fi (or the Local URL on
the phone itself). To keep it running with the screen off, run
`termux-wake-lock` first.

## Configuration

Edit `config.py`:

- `SYMBOLS`, `INTERVALS` — markets offered in the dashboard dropdowns
- `WEIGHTS` — importance of each strategy in the composite score
- `SIGNAL_THRESHOLD` — how much confluence is needed to fire a signal
- `REFRESH_SECONDS` — background analysis interval
- `PORT` — web server port

Signal history persists to `signals.json`.

> Note: if `api.binance.com` is geo-restricted where you are, the bot
> automatically falls back to `data-api.binance.vision` for market data.
> Futures fundamentals (funding/OI) are skipped gracefully when unavailable.

## Disclaimer

Educational tool — not financial advice. Signals are algorithmic confluence
scores, not guarantees.
# New-project
