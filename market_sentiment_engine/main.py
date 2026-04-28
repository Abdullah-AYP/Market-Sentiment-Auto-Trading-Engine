from __future__ import annotations

import argparse
import logging

from .alerts import SignalPublisher
from .config import Settings
from .data_sources import BinanceMarketDataClient, GoogleNewsClient
from .decision import DecisionTreeStrategy
from .engine import MarketSentimentTradingEngine
from .sentiment import OpenAISentimentAnalyzer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market sentiment auto-trading engine")
    parser.add_argument("--once", action="store_true", help="Run only one cycle")
    parser.add_argument(
        "--all-symbols",
        action="store_true",
        help="When used with --once, run one cycle for every symbol in TRADING_SYMBOLS",
    )
    parser.add_argument("--max-cycles", type=int, default=None, help="Maximum cycles when running loop mode")
    parser.add_argument("--interval-seconds", type=int, default=None, help="Override cycle interval seconds")
    parser.add_argument("--symbol", type=str, default=None, help="Trading symbol, e.g. XRPUSDT")
    parser.add_argument("--news-query", type=str, default=None, help="News query string")
    parser.add_argument("--news-limit", type=int, default=None, help="Maximum headlines per cycle")
    parser.add_argument("--quiet", action="store_true", help="Disable stdout payload print")
    return parser.parse_args()


def build_engine(settings: Settings) -> MarketSentimentTradingEngine:
    market_client = BinanceMarketDataClient(timeout_seconds=settings.request_timeout_seconds)
    news_client = GoogleNewsClient(timeout_seconds=settings.request_timeout_seconds)
    sentiment_analyzer = OpenAISentimentAnalyzer(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
    )
    strategy = DecisionTreeStrategy(
        bullish_threshold=settings.bullish_threshold,
        bearish_threshold=settings.bearish_threshold,
        min_sentiment_confidence=settings.min_sentiment_confidence,
        neutral_band=settings.neutral_band,
        account_equity_usdt=settings.account_equity_usdt,
        risk_per_trade_pct=settings.risk_per_trade_pct,
        base_position_size_pct=settings.base_position_size_pct,
        min_position_size_pct=settings.min_position_size_pct,
        max_position_size_pct=settings.max_position_size_pct,
        max_volatility_24h_pct=settings.max_volatility_24h_pct,
        stop_loss_min_pct=settings.stop_loss_min_pct,
        stop_loss_max_pct=settings.stop_loss_max_pct,
        take_profit_rr=settings.take_profit_rr,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        daily_loss_used_pct=settings.daily_loss_used_pct,
        momentum_override_pct=settings.momentum_override_pct,
        min_trade_confidence=settings.min_trade_confidence,
    )
    publisher = SignalPublisher(settings.signal_output_path, print_to_stdout=settings.enable_alert_print)
    return MarketSentimentTradingEngine(
        settings=settings,
        market_client=market_client,
        news_client=news_client,
        sentiment_analyzer=sentiment_analyzer,
        strategy=strategy,
        publisher=publisher,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    symbol_override = args.symbol.upper() if args.symbol else None
    settings = Settings.from_env().with_overrides(
        trading_symbol=symbol_override,
        trading_symbols=(symbol_override,) if symbol_override else None,
        news_query=args.news_query,
        news_limit=args.news_limit,
        run_interval_seconds=args.interval_seconds,
        enable_alert_print=False if args.quiet else None,
    )

    engine = build_engine(settings)

    if args.once:
        if args.all_symbols:
            engine.run_multi_cycle(settings.trading_symbols)
        else:
            engine.run_cycle()
    else:
        engine.run_forever(max_cycles=args.max_cycles)

    return 0
