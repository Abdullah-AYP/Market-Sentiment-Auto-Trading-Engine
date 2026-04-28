from __future__ import annotations

import os
from dataclasses import dataclass, replace

from dotenv import load_dotenv


load_dotenv()


def _as_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _as_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _normalize_symbol(raw_value: str) -> str:
    return "".join(ch for ch in raw_value.upper().strip() if ch.isalnum())


def _as_symbol_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default

    symbols: list[str] = []
    seen: set[str] = set()
    for token in raw_value.split(","):
        symbol = _normalize_symbol(token)
        if not symbol or symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)

    return tuple(symbols) if symbols else default


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_base_url: str | None
    openai_model: str
    trading_symbol: str
    trading_symbols: tuple[str, ...]
    news_query: str
    news_limit: int
    run_interval_seconds: int
    signal_output_path: str
    request_timeout_seconds: int
    enable_alert_print: bool
    account_equity_usdt: float
    risk_per_trade_pct: float
    base_position_size_pct: float
    min_position_size_pct: float
    max_position_size_pct: float
    max_volatility_24h_pct: float
    stop_loss_min_pct: float
    stop_loss_max_pct: float
    take_profit_rr: float
    max_daily_loss_pct: float
    daily_loss_used_pct: float
    bullish_threshold: float
    bearish_threshold: float
    neutral_band: float
    min_sentiment_confidence: float
    momentum_override_pct: float
    min_trade_confidence: float
    paper_starting_cash_usdt: float
    paper_fee_bps: float
    paper_slippage_bps: float
    paper_min_notional_usdt: float
    paper_max_trades_per_day: int
    paper_max_daily_drawdown_pct: float
    paper_state_path: str
    paper_trades_path: str
    n8n_webhook_secret: str | None
    n8n_signature_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        primary_symbol = _normalize_symbol(os.getenv("TRADING_SYMBOL", "XRPUSDT")) or "XRPUSDT"
        symbols = _as_symbol_list("TRADING_SYMBOLS", (primary_symbol,))
        if primary_symbol not in symbols:
            symbols = (primary_symbol, *symbols)

        account_equity_usdt = _as_float("ACCOUNT_EQUITY_USDT", 1000.0)
        paper_starting_cash_usdt = _as_float("PAPER_STARTING_CASH_USDT", account_equity_usdt)
        raw_n8n_secret = os.getenv("N8N_WEBHOOK_SECRET")
        n8n_webhook_secret = raw_n8n_secret.strip() if raw_n8n_secret and raw_n8n_secret.strip() else None

        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            trading_symbol=primary_symbol,
            trading_symbols=symbols,
            news_query=os.getenv("NEWS_QUERY", "XRP cryptocurrency"),
            news_limit=_as_int("NEWS_LIMIT", 20),
            run_interval_seconds=_as_int("RUN_INTERVAL_SECONDS", 300),
            signal_output_path=os.getenv("SIGNAL_OUTPUT_PATH", "signals/signals.jsonl"),
            request_timeout_seconds=_as_int("REQUEST_TIMEOUT_SECONDS", 15),
            enable_alert_print=_as_bool("ENABLE_ALERT_PRINT", True),
            account_equity_usdt=account_equity_usdt,
            risk_per_trade_pct=_as_float("RISK_PER_TRADE_PCT", 1.0),
            base_position_size_pct=_as_float("BASE_POSITION_SIZE_PCT", 10.0),
            min_position_size_pct=_as_float("MIN_POSITION_SIZE_PCT", 2.0),
            max_position_size_pct=_as_float("MAX_POSITION_SIZE_PCT", 20.0),
            max_volatility_24h_pct=_as_float("MAX_VOLATILITY_24H_PCT", 12.0),
            stop_loss_min_pct=_as_float("STOP_LOSS_MIN_PCT", 1.0),
            stop_loss_max_pct=_as_float("STOP_LOSS_MAX_PCT", 4.0),
            take_profit_rr=_as_float("TAKE_PROFIT_RR", 2.0),
            max_daily_loss_pct=_as_float("MAX_DAILY_LOSS_PCT", 3.0),
            daily_loss_used_pct=_as_float("DAILY_LOSS_USED_PCT", 0.0),
            bullish_threshold=_as_float("BULLISH_THRESHOLD", 0.22),
            bearish_threshold=_as_float("BEARISH_THRESHOLD", -0.22),
            neutral_band=_as_float("NEUTRAL_BAND", 0.08),
            min_sentiment_confidence=_as_float("MIN_SENTIMENT_CONFIDENCE", 0.45),
            momentum_override_pct=_as_float("MOMENTUM_OVERRIDE_PCT", 1.2),
            min_trade_confidence=_as_float("MIN_TRADE_CONFIDENCE", 0.52),
            paper_starting_cash_usdt=paper_starting_cash_usdt,
            paper_fee_bps=_as_float("PAPER_FEE_BPS", 10.0),
            paper_slippage_bps=_as_float("PAPER_SLIPPAGE_BPS", 2.0),
            paper_min_notional_usdt=_as_float("PAPER_MIN_NOTIONAL_USDT", 5.0),
            paper_max_trades_per_day=max(1, _as_int("PAPER_MAX_TRADES_PER_DAY", 24)),
            paper_max_daily_drawdown_pct=max(0.1, _as_float("PAPER_MAX_DAILY_DRAWDOWN_PCT", 4.0)),
            paper_state_path=os.getenv("PAPER_STATE_PATH", "signals/paper_state.json"),
            paper_trades_path=os.getenv("PAPER_TRADES_PATH", "signals/paper_trades.jsonl"),
            n8n_webhook_secret=n8n_webhook_secret,
            n8n_signature_ttl_seconds=max(30, _as_int("N8N_SIGNATURE_TTL_SECONDS", 300)),
        )

    def with_overrides(self, **overrides: object) -> "Settings":
        valid_overrides = {key: value for key, value in overrides.items() if value is not None}
        return replace(self, **valid_overrides)
