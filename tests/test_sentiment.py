from market_sentiment_engine.models import MarketSnapshot, NewsItem
from market_sentiment_engine.sentiment import OpenAISentimentAnalyzer


def _sample_market() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="XRPUSDT",
        price=1.23,
        change_percent_24h=1.0,
        volume_24h=1000000.0,
        timestamp="2026-01-01T00:00:00+00:00",
    )


def _sample_news() -> list[NewsItem]:
    return [
        NewsItem(
            title="XRP rally continues amid adoption news",
            summary="",
            source="test",
            published_at="",
            url="",
        )
    ]


def test_normalize_api_key_strips_bearer_and_quotes() -> None:
    raw = '  "Bearer sk-test-123" '
    normalized = OpenAISentimentAnalyzer._normalize_api_key(raw)
    assert normalized == "sk-test-123"


def test_github_token_without_base_url_uses_fallback_with_reason() -> None:
    analyzer = OpenAISentimentAnalyzer(
        api_key="github_pat_example_token",
        model="gpt-4o-mini",
        base_url=None,
    )
    result = analyzer.analyze(_sample_news(), _sample_market())
    assert result.model_source == "fallback"
    assert "OPENAI_BASE_URL" in result.rationale
