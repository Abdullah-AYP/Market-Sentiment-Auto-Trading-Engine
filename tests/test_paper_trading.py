from pathlib import Path

from market_sentiment_engine.paper_trading import PaperTradeExecutor


def _payload(
    *,
    symbol: str = "XRPUSDT",
    action: str,
    price: float,
    confidence: float = 0.8,
    trade_allowed: bool = True,
    position_size_usdt: float = 100.0,
    sentiment_score: float = 0.4,
) -> dict[str, object]:
    return {
        "signal": {
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "price": price,
            "timestamp": "2026-04-18T00:00:00+00:00",
            "risk_management": {
                "trade_allowed": trade_allowed,
                "position_size_usdt": position_size_usdt,
            },
        },
        "market": {
            "symbol": symbol,
            "price": price,
            "change_percent_24h": 1.0,
            "volume_24h": 1000000.0,
            "timestamp": "2026-04-18T00:00:00+00:00",
        },
        "sentiment": {
            "score": sentiment_score,
            "confidence": 0.7,
            "model_source": "gpt-4o-mini",
            "rationale": "test",
        },
        "headlines": ["test"],
    }


def test_buy_then_sell_cycle_updates_positions_and_trades(tmp_path: Path) -> None:
    executor = PaperTradeExecutor(
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
        starting_cash_usdt=1000.0,
        fee_bps=10.0,
        slippage_bps=2.0,
        min_notional_usdt=5.0,
    )

    buy_result = executor.apply_signal_payload(_payload(action="BUY", price=2.0, position_size_usdt=120.0))
    assert buy_result["status"] == "executed"
    assert buy_result["paper"]["positions_count"] == 1

    sell_result = executor.apply_signal_payload(_payload(action="SELL", price=2.2, position_size_usdt=0.0))
    assert sell_result["status"] == "executed"
    assert sell_result["paper"]["positions_count"] == 0

    trades = executor.read_recent_trades(limit=10)
    assert len(trades) == 2
    assert trades[0]["side"] == "BUY"
    assert trades[1]["side"] == "SELL"


def test_buy_blocked_when_risk_gate_is_false(tmp_path: Path) -> None:
    executor = PaperTradeExecutor(
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
        starting_cash_usdt=500.0,
    )

    result = executor.apply_signal_payload(
        _payload(action="BUY", price=1.5, trade_allowed=False, position_size_usdt=80.0)
    )
    assert result["status"] == "skipped"
    assert "Risk gate blocked entry" in result["reason"]
    assert result["paper"]["positions_count"] == 0


def test_hold_signal_is_skipped_without_trade(tmp_path: Path) -> None:
    executor = PaperTradeExecutor(
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
        starting_cash_usdt=750.0,
    )

    result = executor.apply_signal_payload(_payload(action="HOLD", price=1.2))
    assert result["status"] == "skipped"
    assert result["action"] == "HOLD"
    assert result["paper"]["positions_count"] == 0


def test_buy_blocked_after_daily_trade_limit(tmp_path: Path) -> None:
    executor = PaperTradeExecutor(
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
        starting_cash_usdt=1000.0,
        max_trades_per_day=1,
    )

    first = executor.apply_signal_payload(_payload(action="BUY", price=2.0, position_size_usdt=100.0))
    assert first["status"] == "executed"

    second = executor.apply_signal_payload(_payload(action="BUY", price=2.1, position_size_usdt=100.0))
    assert second["status"] == "skipped"
    assert "Daily trade limit reached" in second["reason"]


def test_drawdown_hard_stop_blocks_new_buy_entries(tmp_path: Path) -> None:
    executor = PaperTradeExecutor(
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
        starting_cash_usdt=1000.0,
        max_daily_drawdown_pct=1.0,
    )

    buy = executor.apply_signal_payload(_payload(action="BUY", price=2.0, position_size_usdt=800.0))
    assert buy["status"] == "executed"

    # Mark position down significantly to trigger the daily hard-stop gate.
    executor.apply_signal_payload(_payload(action="HOLD", price=1.0, position_size_usdt=0.0))

    blocked = executor.apply_signal_payload(_payload(action="BUY", price=1.0, position_size_usdt=50.0))
    assert blocked["status"] == "skipped"
    assert "Daily drawdown" in blocked["reason"]
    assert blocked["paper"]["daily_guardrails"]["hard_stop_active"] is True

    # SELL remains allowed so the simulator can reduce exposure when needed.
    sell = executor.apply_signal_payload(_payload(action="SELL", price=1.0, position_size_usdt=0.0))
    assert sell["status"] == "executed"
