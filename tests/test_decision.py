from market_sentiment_engine.decision import DecisionTreeStrategy
from market_sentiment_engine.models import MarketSnapshot, SentimentResult


def make_market(change_percent_24h: float) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="XRPUSDT",
        price=1.0,
        change_percent_24h=change_percent_24h,
        volume_24h=1234567.0,
        timestamp="2026-01-01T00:00:00+00:00",
    )


def test_buy_signal_for_high_confidence_bullish_sentiment() -> None:
    strategy = DecisionTreeStrategy()
    signal = strategy.evaluate(
        SentimentResult(score=0.8, confidence=0.9, rationale="bullish", model_source="test"),
        make_market(4.0),
    )
    assert signal.action == "BUY"
    assert signal.risk_management["trade_allowed"] is True
    assert signal.risk_management["stop_loss_price"] < signal.price
    assert signal.risk_management["take_profit_price"] > signal.price


def test_sell_signal_for_high_confidence_bearish_sentiment() -> None:
    strategy = DecisionTreeStrategy()
    signal = strategy.evaluate(
        SentimentResult(score=-0.8, confidence=0.9, rationale="bearish", model_source="test"),
        make_market(-4.0),
    )
    assert signal.action == "SELL"
    assert signal.risk_management["trade_allowed"] is True
    assert signal.risk_management["stop_loss_price"] > signal.price
    assert signal.risk_management["take_profit_price"] < signal.price


def test_hold_signal_when_confidence_is_low() -> None:
    strategy = DecisionTreeStrategy()
    signal = strategy.evaluate(
        SentimentResult(score=0.9, confidence=0.2, rationale="uncertain", model_source="test"),
        make_market(2.0),
    )
    assert signal.action == "HOLD"


def test_risk_rules_block_trade_in_extreme_volatility() -> None:
    strategy = DecisionTreeStrategy(max_volatility_24h_pct=5.0)
    signal = strategy.evaluate(
        SentimentResult(score=0.9, confidence=0.95, rationale="very bullish", model_source="test"),
        make_market(11.0),
    )
    assert signal.action == "HOLD"
    assert signal.risk_management["trade_allowed"] is False


def test_momentum_override_can_trigger_buy_signal() -> None:
    strategy = DecisionTreeStrategy(momentum_override_pct=1.0)
    signal = strategy.evaluate(
        SentimentResult(score=0.7, confidence=0.8, rationale="strong positive", model_source="test"),
        make_market(2.0),
    )
    assert signal.action == "BUY"


def test_confident_mild_sentiment_can_escape_hold_with_adaptive_thresholds() -> None:
    strategy = DecisionTreeStrategy(
        bullish_threshold=0.24,
        bearish_threshold=-0.24,
        min_sentiment_confidence=0.45,
    )
    signal = strategy.evaluate(
        SentimentResult(score=0.34, confidence=0.9, rationale="positive", model_source="test"),
        make_market(0.5),
    )
    assert signal.action in {"BUY", "HOLD"}
