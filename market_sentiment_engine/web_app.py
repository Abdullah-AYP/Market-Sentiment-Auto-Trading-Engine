from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .data_sources import BinanceMarketDataClient
from .main import build_engine
from .paper_trading import PaperTradeExecutor


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"
RUN_LOCK = threading.Lock()
PAPER_LOCK = threading.Lock()

app = FastAPI(title="Market Sentiment Auto-Trading Engine API", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def _runtime_settings() -> Settings:
    return Settings.from_env().with_overrides(enable_alert_print=False)


def _market_client(settings: Settings) -> BinanceMarketDataClient:
    return BinanceMarketDataClient(timeout_seconds=settings.request_timeout_seconds)


def _paper_executor(settings: Settings) -> PaperTradeExecutor:
    return PaperTradeExecutor(
        state_path=settings.paper_state_path,
        trades_path=settings.paper_trades_path,
        starting_cash_usdt=settings.paper_starting_cash_usdt,
        fee_bps=settings.paper_fee_bps,
        slippage_bps=settings.paper_slippage_bps,
        min_notional_usdt=settings.paper_min_notional_usdt,
        max_trades_per_day=settings.paper_max_trades_per_day,
        max_daily_drawdown_pct=settings.paper_max_daily_drawdown_pct,
    )


async def _verify_n8n_request_signature(request: Request, settings: Settings) -> None:
    """
    If N8N_WEBHOOK_SECRET is configured, require signed requests.
    Signature base string:
    {timestamp}.{method}.{path}.{query}.{raw_body}
    """
    secret = settings.n8n_webhook_secret
    if not secret:
        return

    timestamp = request.headers.get("x-webhook-timestamp", "").strip()
    raw_signature = request.headers.get("x-webhook-signature", "").strip()
    if not timestamp or not raw_signature:
        raise HTTPException(status_code=401, detail="Missing webhook signature headers.")

    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid webhook timestamp header.") from exc

    max_age_seconds = max(settings.n8n_signature_ttl_seconds, 30)
    if abs(int(time.time()) - timestamp_int) > max_age_seconds:
        raise HTTPException(status_code=401, detail="Webhook signature timestamp expired.")

    normalized_signature = raw_signature
    if raw_signature.lower().startswith("sha256="):
        normalized_signature = raw_signature.split("=", 1)[1]

    body = await request.body()
    signature_base = (
        f"{timestamp}.{request.method.upper()}.{request.url.path}.{request.url.query}".encode("utf-8")
        + b"."
        + body
    )
    expected = hmac.new(secret.encode("utf-8"), signature_base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(normalized_signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")


def _normalize_symbol(symbol: str | None) -> str | None:
    if symbol is None:
        return None
    normalized = "".join(ch for ch in symbol.upper().strip() if ch.isalnum())
    return normalized or None


def _validate_symbol(symbol: str | None, settings: Settings) -> str | None:
    normalized = _normalize_symbol(symbol)
    if normalized is None:
        return None
    if normalized not in settings.trading_symbols:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported symbol '{normalized}'. Allowed: {', '.join(settings.trading_symbols)}",
        )
    return normalized


def _read_recent_signals(limit: int, symbol: str | None = None) -> list[dict[str, Any]]:
    settings = _runtime_settings()
    signals_path = Path(settings.signal_output_path)
    if not signals_path.exists():
        return []

    with signals_path.open("r", encoding="utf-8") as file_handle:
        lines = file_handle.readlines()

    parsed_payloads: list[dict[str, Any]] = []
    for line in lines:
        cleaned_line = line.strip()
        if not cleaned_line:
            continue
        try:
            payload = json.loads(cleaned_line)
            payload_symbol = str(payload.get("signal", {}).get("symbol", "")).upper()
            if symbol and payload_symbol != symbol:
                continue
            parsed_payloads.append(payload)
        except json.JSONDecodeError:
            continue

    return parsed_payloads[-limit:]


def _summarize(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    confidence_sum = 0.0
    model_sources: dict[str, int] = {}

    for payload in payloads:
        signal = payload.get("signal", {})
        sentiment = payload.get("sentiment", {})
        action = str(signal.get("action", "HOLD")).upper()
        if action not in counts:
            action = "HOLD"
        counts[action] += 1
        confidence_sum += float(signal.get("confidence", 0.0) or 0.0)

        source = str(sentiment.get("model_source", "unknown"))
        model_sources[source] = model_sources.get(source, 0) + 1

    total = len(payloads)
    avg_confidence = (confidence_sum / total) if total else 0.0
    latest_timestamp = payloads[-1].get("signal", {}).get("timestamp") if total else None

    return {
        "total": total,
        "counts": counts,
        "avg_confidence": avg_confidence,
        "latest_timestamp": latest_timestamp,
        "model_sources": model_sources,
    }


def _compact_n8n_item(payload: dict[str, Any]) -> dict[str, Any]:
    signal = payload.get("signal", {})
    sentiment = payload.get("sentiment", {})
    market = payload.get("market", {})
    risk = signal.get("risk_management", {})

    return {
        "symbol": signal.get("symbol") or market.get("symbol"),
        "action": signal.get("action", "HOLD"),
        "signal_confidence": signal.get("confidence", 0.0),
        "timestamp": signal.get("timestamp") or market.get("timestamp"),
        "trade_allowed": bool(risk.get("trade_allowed", False)),
        "position_size_pct": risk.get("position_size_pct", 0.0),
        "position_size_usdt": risk.get("position_size_usdt", 0.0),
        "stop_loss_price": risk.get("stop_loss_price"),
        "take_profit_price": risk.get("take_profit_price"),
        "sentiment_score": sentiment.get("score", 0.0),
        "sentiment_confidence": sentiment.get("confidence", 0.0),
        "model_source": sentiment.get("model_source", "unknown"),
        "market_price": market.get("price"),
        "market_change_percent_24h": market.get("change_percent_24h"),
    }


def _validate_interval(interval: str) -> str:
    allowed = {
        "1m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1h",
        "2h",
        "4h",
        "6h",
        "8h",
        "12h",
        "1d",
    }
    normalized = interval.strip()
    if normalized not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported interval '{interval}'.")
    return normalized


@app.get("/")
def dashboard() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="Frontend file is missing.")
    return FileResponse(index_path)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def config() -> dict[str, Any]:
    settings = _runtime_settings()
    return {
        "trading_symbol": settings.trading_symbol,
        "trading_symbols": list(settings.trading_symbols),
        "news_query": settings.news_query,
        "news_limit": settings.news_limit,
        "run_interval_seconds": settings.run_interval_seconds,
        "openai_model": settings.openai_model,
        "openai_base_url": settings.openai_base_url,
        "openai_api_key_set": bool(settings.openai_api_key),
        "signal_output_path": settings.signal_output_path,
        "paper_state_path": settings.paper_state_path,
        "paper_trades_path": settings.paper_trades_path,
        "paper_starting_cash_usdt": settings.paper_starting_cash_usdt,
        "paper_fee_bps": settings.paper_fee_bps,
        "paper_slippage_bps": settings.paper_slippage_bps,
        "paper_min_notional_usdt": settings.paper_min_notional_usdt,
        "paper_max_trades_per_day": settings.paper_max_trades_per_day,
        "paper_max_daily_drawdown_pct": settings.paper_max_daily_drawdown_pct,
        "n8n_webhook_auth_enabled": bool(settings.n8n_webhook_secret),
        "n8n_signature_ttl_seconds": settings.n8n_signature_ttl_seconds,
    }


@app.get("/api/terminal/snapshots")
def terminal_snapshots() -> dict[str, Any]:
    settings = _runtime_settings()
    client = _market_client(settings)
    snapshots = client.fetch_snapshots(settings.trading_symbols)

    items = [
        {
            "symbol": snapshot.symbol,
            "price": snapshot.price,
            "change_percent_24h": snapshot.change_percent_24h,
            "volume_24h": snapshot.volume_24h,
            "timestamp": snapshot.timestamp,
        }
        for snapshot in snapshots
    ]
    return {"items": items}


@app.get("/api/terminal/order-book")
def terminal_order_book(
    symbol: str | None = Query(default=None),
    limit: int = Query(default=20, ge=5, le=100),
) -> dict[str, Any]:
    settings = _runtime_settings()
    selected_symbol = _validate_symbol(symbol, settings) or settings.trading_symbol
    client = _market_client(settings)
    return client.fetch_order_book(selected_symbol, limit=limit)


@app.get("/api/terminal/klines")
def terminal_klines(
    symbol: str | None = Query(default=None),
    interval: str = Query(default="15m"),
    limit: int = Query(default=120, ge=20, le=1000),
) -> dict[str, Any]:
    settings = _runtime_settings()
    selected_symbol = _validate_symbol(symbol, settings) or settings.trading_symbol
    normalized_interval = _validate_interval(interval)
    client = _market_client(settings)

    return {
        "symbol": selected_symbol,
        "interval": normalized_interval,
        "items": client.fetch_klines(selected_symbol, interval=normalized_interval, limit=limit),
    }


@app.get("/api/latest-signal")
def latest_signal(symbol: str | None = Query(default=None)) -> dict[str, Any]:
    settings = _runtime_settings()
    selected_symbol = _validate_symbol(symbol, settings)
    payloads = _read_recent_signals(limit=1, symbol=selected_symbol)
    if not payloads:
        raise HTTPException(status_code=404, detail="No signal data found. Run at least one cycle first.")
    return payloads[-1]


@app.get("/api/signals")
def signal_history(
    limit: int = Query(default=20, ge=1, le=500),
    symbol: str | None = Query(default=None),
) -> dict[str, list[dict[str, Any]]]:
    settings = _runtime_settings()
    selected_symbol = _validate_symbol(symbol, settings)
    payloads = _read_recent_signals(limit=limit, symbol=selected_symbol)
    return {"items": payloads}


@app.get("/api/summary")
def summary(
    limit: int = Query(default=120, ge=1, le=1000),
    symbol: str | None = Query(default=None),
) -> dict[str, Any]:
    settings = _runtime_settings()
    selected_symbol = _validate_symbol(symbol, settings)
    payloads = _read_recent_signals(limit=limit, symbol=selected_symbol)
    data = _summarize(payloads)
    data["symbol"] = selected_symbol
    return data


@app.get("/api/paper/state")
def paper_state() -> dict[str, Any]:
    settings = _runtime_settings()
    executor = _paper_executor(settings)
    return executor.get_state_snapshot()


@app.get("/api/paper/trades")
def paper_trades(limit: int = Query(default=50, ge=1, le=1000)) -> dict[str, Any]:
    settings = _runtime_settings()
    executor = _paper_executor(settings)
    return {"items": executor.read_recent_trades(limit=limit)}


@app.post("/api/paper/apply-latest")
def paper_apply_latest(symbol: str | None = Query(default=None)) -> dict[str, Any]:
    settings = _runtime_settings()
    selected_symbol = _validate_symbol(symbol, settings)
    payloads = _read_recent_signals(limit=1, symbol=selected_symbol)

    if not payloads:
        raise HTTPException(status_code=404, detail="No signal data found. Run at least one cycle first.")

    with PAPER_LOCK:
        executor = _paper_executor(settings)
        return executor.apply_signal_payload(payloads[-1])


@app.post("/api/paper/reset")
def paper_reset(clear_trades: bool = Query(default=False)) -> dict[str, Any]:
    settings = _runtime_settings()
    with PAPER_LOCK:
        executor = _paper_executor(settings)
        snapshot = executor.reset(clear_trades=clear_trades)

    return {
        "status": "ok",
        "cleared_trades": clear_trades,
        "paper": snapshot,
    }


@app.get("/api/n8n/latest-signal")
async def n8n_latest_signal(request: Request, symbol: str | None = Query(default=None)) -> dict[str, Any]:
    """
    Stable, n8n-friendly endpoint that never returns 404 for missing data.
    """
    settings = _runtime_settings()
    await _verify_n8n_request_signature(request, settings)
    selected_symbol = _validate_symbol(symbol, settings)
    payloads = _read_recent_signals(limit=1, symbol=selected_symbol)

    if not payloads:
        return {
            "status": "no_data",
            "item": None,
            "payload": None,
        }

    payload = payloads[-1]
    return {
        "status": "ok",
        "item": _compact_n8n_item(payload),
        "payload": payload,
    }


@app.post("/api/run-once")
def run_once(symbol: str | None = Query(default=None)) -> dict[str, Any]:
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A cycle is already running.")

    try:
        settings = _runtime_settings()
        selected_symbol = _validate_symbol(symbol, settings) or settings.trading_symbol
        engine = build_engine(settings)
        payload = engine.run_cycle(symbol=selected_symbol)
        return {"status": "ok", "payload": payload}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cycle execution failed: {exc}") from exc
    finally:
        RUN_LOCK.release()


@app.post("/api/run-all")
def run_all() -> dict[str, Any]:
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A cycle is already running.")

    try:
        settings = _runtime_settings()
        engine = build_engine(settings)
        payloads = engine.run_multi_cycle(list(settings.trading_symbols))
        return {"status": "ok", "count": len(payloads), "items": payloads}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Multi-symbol execution failed: {exc}") from exc
    finally:
        RUN_LOCK.release()


@app.post("/api/n8n/run-once")
async def n8n_run_once(request: Request, symbol: str | None = Query(default=None)) -> dict[str, Any]:
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A cycle is already running.")

    try:
        settings = _runtime_settings()
        await _verify_n8n_request_signature(request, settings)
        selected_symbol = _validate_symbol(symbol, settings) or settings.trading_symbol
        engine = build_engine(settings)
        payload = engine.run_cycle(symbol=selected_symbol)
        return {
            "status": "ok",
            "item": _compact_n8n_item(payload),
            "payload": payload,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cycle execution failed: {exc}") from exc
    finally:
        RUN_LOCK.release()


@app.post("/api/n8n/run-once-paper")
async def n8n_run_once_paper(request: Request, symbol: str | None = Query(default=None)) -> dict[str, Any]:
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A cycle is already running.")

    try:
        settings = _runtime_settings()
        await _verify_n8n_request_signature(request, settings)
        selected_symbol = _validate_symbol(symbol, settings) or settings.trading_symbol
        engine = build_engine(settings)
        payload = engine.run_cycle(symbol=selected_symbol)

        with PAPER_LOCK:
            executor = _paper_executor(settings)
            paper_result = executor.apply_signal_payload(payload)

        return {
            "status": "ok",
            "item": _compact_n8n_item(payload),
            "paper": paper_result,
            "payload": payload,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cycle execution failed: {exc}") from exc
    finally:
        RUN_LOCK.release()


@app.post("/api/n8n/run-all")
async def n8n_run_all(request: Request) -> dict[str, Any]:
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A cycle is already running.")

    try:
        settings = _runtime_settings()
        await _verify_n8n_request_signature(request, settings)
        engine = build_engine(settings)
        payloads = engine.run_multi_cycle(list(settings.trading_symbols))
        return {
            "status": "ok",
            "count": len(payloads),
            "items": [_compact_n8n_item(payload) for payload in payloads],
            "payloads": payloads,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Multi-symbol execution failed: {exc}") from exc
    finally:
        RUN_LOCK.release()
