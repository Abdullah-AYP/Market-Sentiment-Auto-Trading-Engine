from __future__ import annotations

import json
from pathlib import Path

from .models import MarketSnapshot, NewsItem, SentimentResult, TradingSignal


class SignalPublisher:
    def __init__(self, output_path: str, print_to_stdout: bool = True) -> None:
        self.output_path = output_path
        self.print_to_stdout = print_to_stdout

    def publish(
        self,
        signal: TradingSignal,
        sentiment: SentimentResult,
        market: MarketSnapshot,
        news_items: list[NewsItem],
    ) -> dict[str, object]:
        payload = {
            "signal": signal.to_dict(),
            "sentiment": {
                "score": sentiment.score,
                "confidence": sentiment.confidence,
                "rationale": sentiment.rationale,
                "model_source": sentiment.model_source,
            },
            "market": {
                "symbol": market.symbol,
                "price": market.price,
                "change_percent_24h": market.change_percent_24h,
                "volume_24h": market.volume_24h,
                "timestamp": market.timestamp,
            },
            "headlines": [item.title for item in news_items[:8]],
        }

        output_file = Path(self.output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

        if self.print_to_stdout:
            print(json.dumps(payload, indent=2, ensure_ascii=True))

        return payload
