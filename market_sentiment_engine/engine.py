from __future__ import annotations

import logging
import time

from .alerts import SignalPublisher
from .config import Settings
from .data_sources import BinanceMarketDataClient, GoogleNewsClient
from .decision import DecisionTreeStrategy
from .sentiment import OpenAISentimentAnalyzer


LOGGER = logging.getLogger(__name__)


class MarketSentimentTradingEngine:
    def __init__(
        self,
        settings: Settings,
        market_client: BinanceMarketDataClient,
        news_client: GoogleNewsClient,
        sentiment_analyzer: OpenAISentimentAnalyzer,
        strategy: DecisionTreeStrategy,
        publisher: SignalPublisher,
    ) -> None:
        self.settings = settings
        self.market_client = market_client
        self.news_client = news_client
        self.sentiment_analyzer = sentiment_analyzer
        self.strategy = strategy
        self.publisher = publisher

    def run_cycle(self, symbol: str | None = None) -> dict[str, object]:
        target_symbol = (symbol or self.settings.trading_symbol).upper()
        news_query = self._resolve_news_query(target_symbol)

        market = self.market_client.fetch_snapshot(target_symbol)
        news_items = self.news_client.fetch_news(news_query, self.settings.news_limit)
        sentiment = self.sentiment_analyzer.analyze(news_items, market)
        signal = self.strategy.evaluate(sentiment, market)
        return self.publisher.publish(signal, sentiment, market, news_items)

    def run_multi_cycle(self, symbols: tuple[str, ...] | list[str] | None = None) -> list[dict[str, object]]:
        targets = tuple(symbols) if symbols else self.settings.trading_symbols
        payloads: list[dict[str, object]] = []

        for symbol in targets:
            payloads.append(self.run_cycle(symbol=symbol))

        return payloads

    def run_forever(self, max_cycles: int | None = None) -> None:
        cycle_count = 0
        while True:
            cycle_count += 1
            try:
                payloads = self.run_multi_cycle(self.settings.trading_symbols)
                summary = []
                for payload in payloads:
                    signal = payload.get("signal", {})
                    summary.append(f"{signal.get('symbol')}:{signal.get('action')}")

                LOGGER.info(
                    "Cycle %s completed: %s",
                    cycle_count,
                    ", ".join(summary),
                )
            except Exception as exc:  # pragma: no cover
                LOGGER.exception("Cycle %s failed: %s", cycle_count, exc)

            if max_cycles is not None and cycle_count >= max_cycles:
                return

            time.sleep(self.settings.run_interval_seconds)

    def _resolve_news_query(self, symbol: str) -> str:
        asset = symbol[:-4] if symbol.endswith("USDT") else symbol
        query_template = self.settings.news_query

        if "{asset}" in query_template:
            return query_template.replace("{asset}", asset)

        if symbol == self.settings.trading_symbol:
            return query_template

        return f"{asset} cryptocurrency"
