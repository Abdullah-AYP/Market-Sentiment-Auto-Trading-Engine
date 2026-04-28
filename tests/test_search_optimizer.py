import json
from pathlib import Path

from market_sentiment_engine.config import Settings
from market_sentiment_engine.search_optimizer import (
    SearchConfig,
    beam_search_optimize,
    build_transition_pairs,
    classify_future_move,
    load_observations_from_signals,
)


def test_classify_future_move_respects_threshold() -> None:
    assert classify_future_move(0.20, 0.12) == "BUY"
    assert classify_future_move(-0.20, 0.12) == "SELL"
    assert classify_future_move(0.05, 0.12) == "HOLD"


def test_beam_search_runs_on_signal_history(tmp_path: Path) -> None:
    sample = [
        {
            "market": {
                "symbol": "XRPUSDT",
                "price": 1.00,
                "change_percent_24h": 0.5,
                "volume_24h": 1000,
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
            "sentiment": {
                "score": 0.7,
                "confidence": 0.8,
                "rationale": "positive",
                "model_source": "test",
            },
        },
        {
            "market": {
                "symbol": "XRPUSDT",
                "price": 1.02,
                "change_percent_24h": 0.8,
                "volume_24h": 1100,
                "timestamp": "2026-01-01T00:05:00+00:00",
            },
            "sentiment": {
                "score": -0.6,
                "confidence": 0.8,
                "rationale": "negative",
                "model_source": "test",
            },
        },
        {
            "market": {
                "symbol": "XRPUSDT",
                "price": 1.00,
                "change_percent_24h": -0.9,
                "volume_24h": 1150,
                "timestamp": "2026-01-01T00:10:00+00:00",
            },
            "sentiment": {
                "score": 0.75,
                "confidence": 0.85,
                "rationale": "positive",
                "model_source": "test",
            },
        },
        {
            "market": {
                "symbol": "XRPUSDT",
                "price": 1.03,
                "change_percent_24h": 1.0,
                "volume_24h": 1200,
                "timestamp": "2026-01-01T00:15:00+00:00",
            },
            "sentiment": {
                "score": -0.7,
                "confidence": 0.82,
                "rationale": "negative",
                "model_source": "test",
            },
        },
        {
            "market": {
                "symbol": "XRPUSDT",
                "price": 0.99,
                "change_percent_24h": -1.2,
                "volume_24h": 1250,
                "timestamp": "2026-01-01T00:20:00+00:00",
            },
            "sentiment": {
                "score": 0.8,
                "confidence": 0.87,
                "rationale": "positive",
                "model_source": "test",
            },
        },
        {
            "market": {
                "symbol": "XRPUSDT",
                "price": 1.04,
                "change_percent_24h": 1.4,
                "volume_24h": 1300,
                "timestamp": "2026-01-01T00:25:00+00:00",
            },
            "sentiment": {
                "score": -0.75,
                "confidence": 0.86,
                "rationale": "negative",
                "model_source": "test",
            },
        },
        {
            "market": {
                "symbol": "XRPUSDT",
                "price": 0.98,
                "change_percent_24h": -1.6,
                "volume_24h": 1350,
                "timestamp": "2026-01-01T00:30:00+00:00",
            },
            "sentiment": {
                "score": 0.82,
                "confidence": 0.88,
                "rationale": "positive",
                "model_source": "test",
            },
        },
        {
            "market": {
                "symbol": "XRPUSDT",
                "price": 1.05,
                "change_percent_24h": 1.8,
                "volume_24h": 1400,
                "timestamp": "2026-01-01T00:35:00+00:00",
            },
            "sentiment": {
                "score": 0.10,
                "confidence": 0.40,
                "rationale": "mixed",
                "model_source": "test",
            },
        },
        {
            "market": {
                "symbol": "XRPUSDT",
                "price": 1.06,
                "change_percent_24h": 1.1,
                "volume_24h": 1450,
                "timestamp": "2026-01-01T00:40:00+00:00",
            },
            "sentiment": {
                "score": 0.20,
                "confidence": 0.45,
                "rationale": "mixed",
                "model_source": "test",
            },
        },
    ]

    signals_path = tmp_path / "signals.jsonl"
    signals_path.write_text("\n".join(json.dumps(row) for row in sample), encoding="utf-8")

    observations = load_observations_from_signals(signals_path)
    transitions = build_transition_pairs(observations)

    assert "XRPUSDT" in observations
    assert len(transitions) >= 8

    settings = Settings.from_env()
    best, leaderboard = beam_search_optimize(
        transitions=transitions,
        settings=settings,
        config=SearchConfig(beam_width=3, depth=3),
    )

    assert leaderboard
    assert best.samples == len(transitions)
    assert best.score == leaderboard[0].score
    assert best.parameters.bullish_threshold > 0
    assert best.parameters.bearish_threshold < 0
