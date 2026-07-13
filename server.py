"""AI Trading Signal Bot — FastAPI + WebSocket server.

Run on Termux:
    pkg install python
    pip install -r requirements.txt
    python server.py
Then open http://<phone-local-ip>:8000 from any device on the same network.

The dashboard talks to /ws for realtime ticks, moving candles, analysis
snapshots and signal events. REST endpoints are kept as a fallback.
"""
import asyncio
import contextlib
import json
import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from engine import engine
from stream import Client, manager

BASE_DIR = Path(__file__).parent


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    manager.start()
    yield
    await manager.stop()


app = FastAPI(title="AI Trading Signal Bot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


# ---------------- REST fallback ----------------
@app.get("/api/config")
async def api_config():
    return {
        "symbols": config.SYMBOLS,
        "intervals": config.INTERVALS,
        "default_symbol": config.DEFAULT_SYMBOL,
        "default_interval": config.DEFAULT_INTERVAL,
        "threshold": config.SIGNAL_THRESHOLD,
        "refresh_seconds": config.REFRESH_SECONDS,
    }


@app.get("/api/state")
async def api_state(
    symbol: str = Query(config.DEFAULT_SYMBOL),
    interval: str = Query(config.DEFAULT_INTERVAL),
):
    if symbol not in config.SYMBOLS or interval not in config.INTERVALS:
        return JSONResponse({"error": "invalid symbol or interval"}, status_code=400)
    try:
        return await asyncio.to_thread(engine.get_state, symbol, interval)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/signals")
async def api_signals():
    return list(reversed(engine.signals[-50:]))


# ---------------- realtime WebSocket ----------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    client = Client(ws)

    async def sender():
        while True:
            msg = await client.queue.get()
            await ws.send_text(json.dumps(msg))

    send_task = asyncio.create_task(sender())
    try:
        # hello: config + signal history
        client.send({
            "type": "config",
            "symbols": config.SYMBOLS,
            "intervals": config.INTERVALS,
            "default_symbol": config.DEFAULT_SYMBOL,
            "default_interval": config.DEFAULT_INTERVAL,
            "threshold": config.SIGNAL_THRESHOLD,
        })
        client.send({"type": "signals", "data": list(reversed(engine.signals[-50:]))})
        manager.add_client(client)

        async def push_snapshot(symbol, interval):
            try:
                data = await asyncio.to_thread(engine.get_state, symbol, interval)
                if client.market() == (symbol, interval):
                    client.send({"type": "snapshot", "data": data})
            except Exception as e:  # noqa: BLE001
                client.send({"type": "error", "message": str(e)})

        # initial snapshot for the default market
        asyncio.create_task(push_snapshot(client.symbol, client.interval))

        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("type") == "subscribe":
                symbol = msg.get("symbol", client.symbol)
                interval = msg.get("interval", client.interval)
                if symbol in config.SYMBOLS and interval in config.INTERVALS:
                    manager.retarget(client, symbol, interval)
                    asyncio.create_task(push_snapshot(symbol, interval))
            elif msg.get("type") == "ping":
                client.send({"type": "pong", "t": msg.get("t")})
    except WebSocketDisconnect:
        pass
    finally:
        manager.remove_client(client)
        send_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await send_task


def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


if __name__ == "__main__":
    print("=" * 52)
    print("  AI Trading Signal Bot  (FastAPI + WebSocket)")
    print(f"  Local:   http://127.0.0.1:{config.PORT}")
    print(f"  Network: http://{_local_ip()}:{config.PORT}")
    print("=" * 52)
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
