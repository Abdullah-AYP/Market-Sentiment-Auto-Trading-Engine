from __future__ import annotations

import datetime as dt
from typing import Any

import feedparser
import requests

from .models import MarketSnapshot, NewsItem


class BinanceMarketDataClient:
    TICKER_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"
    DEPTH_URL = "https://api.binance.com/api/v3/depth"
    KLINES_URL = "https://api.binance.com/api/v3/klines"

    def __init__(self, timeout_seconds: int = 15) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch_snapshot(self, symbol: str) -> MarketSnapshot:
        response = requests.get(
            self.TICKER_24H_URL,
            params={"symbol": symbol.upper()},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()

        return MarketSnapshot(
            symbol=symbol.upper(),
            price=float(payload["lastPrice"]),
            change_percent_24h=float(payload["priceChangePercent"]),
            volume_24h=float(payload["volume"]),
            timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
        )

    def fetch_snapshots(self, symbols: tuple[str, ...] | list[str]) -> list[MarketSnapshot]:
        snapshots: list[MarketSnapshot] = []
        for symbol in symbols:
            snapshots.append(self.fetch_snapshot(symbol))
        return snapshots

    def fetch_order_book(self, symbol: str, limit: int = 20) -> dict[str, Any]:
        normalized_symbol = symbol.upper()
        response = requests.get(
            self.DEPTH_URL,
            params={"symbol": normalized_symbol, "limit": limit},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()

        def _normalize_levels(levels: list[list[str]]) -> list[dict[str, float]]:
            normalized: list[dict[str, float]] = []
            running_total = 0.0
            for row in levels:
                price = float(row[0])
                quantity = float(row[1])
                running_total += quantity
                normalized.append(
                    {
                        "price": price,
                        "quantity": quantity,
                        "total": running_total,
                    }
                )
            return normalized

        bids_raw = payload.get("bids", [])
        asks_raw = payload.get("asks", [])

        return {
            "symbol": normalized_symbol,
            "last_update_id": int(payload.get("lastUpdateId", 0) or 0),
            "bids": _normalize_levels(bids_raw),
            "asks": _normalize_levels(asks_raw),
        }

    def fetch_klines(self, symbol: str, interval: str = "15m", limit: int = 120) -> list[dict[str, float | int]]:
        normalized_symbol = symbol.upper()
        response = requests.get(
            self.KLINES_URL,
            params={"symbol": normalized_symbol, "interval": interval, "limit": limit},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload: list[list[Any]] = response.json()

        candles: list[dict[str, float | int]] = []
        for row in payload:
            candles.append(
                {
                    "open_time": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": int(row[6]),
                }
            )

        return candles


class GoogleNewsClient:
    FEED_URL = "https://news.google.com/rss/search"

    def __init__(self, timeout_seconds: int = 15) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch_news(self, query: str, limit: int = 20) -> list[NewsItem]:
        response = requests.get(
            self.FEED_URL,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        parsed = feedparser.parse(response.text)
        news_items: list[NewsItem] = []

        for entry in parsed.entries[:limit]:
            source = entry.get("source")
            source_title = "Google News"
            if isinstance(source, dict):
                source_title = str(source.get("title") or source_title)
            elif source:
                source_title = str(source)

            news_items.append(
                NewsItem(
                    title=str(entry.get("title", "")).strip(),
                    summary=str(entry.get("summary", "")).strip(),
                    source=source_title,
                    published_at=str(entry.get("published", "")).strip(),
                    url=str(entry.get("link", "")).strip(),
                )
            )

        return news_items
