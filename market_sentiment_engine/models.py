from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    source: str
    published_at: str
    url: str


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    price: float
    change_percent_24h: float
    volume_24h: float
    timestamp: str


@dataclass(frozen=True)
class SentimentResult:
    score: float
    confidence: float
    rationale: str
    model_source: str


@dataclass(frozen=True)
class TradingSignal:
    symbol: str
    action: str
    confidence: float
    reasons: list[str]
    risk_management: dict[str, object]
    price: float
    timestamp: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
