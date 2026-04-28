from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


class PaperTradeExecutor:
    def __init__(
        self,
        state_path: str,
        trades_path: str,
        starting_cash_usdt: float,
        fee_bps: float = 10.0,
        slippage_bps: float = 2.0,
        min_notional_usdt: float = 5.0,
        max_trades_per_day: int = 24,
        max_daily_drawdown_pct: float = 4.0,
    ) -> None:
        self.state_path = Path(state_path)
        self.trades_path = Path(trades_path)
        self.starting_cash_usdt = max(float(starting_cash_usdt), 1.0)
        self.fee_bps = max(float(fee_bps), 0.0)
        self.slippage_bps = max(float(slippage_bps), 0.0)
        self.min_notional_usdt = max(float(min_notional_usdt), 0.01)
        self.max_trades_per_day = max(int(max_trades_per_day), 1)
        self.max_daily_drawdown_pct = max(float(max_daily_drawdown_pct), 0.1)

    def reset(self, clear_trades: bool = False) -> dict[str, Any]:
        state = self._default_state()
        self._save_state(state)

        if clear_trades and self.trades_path.exists():
            self.trades_path.unlink()

        return self._build_state_summary(state)

    def get_state_snapshot(self) -> dict[str, Any]:
        return self._build_state_summary(self._load_state())

    def read_recent_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        if not self.trades_path.exists():
            return []

        with self.trades_path.open("r", encoding="utf-8") as handle:
            lines = handle.readlines()

        parsed: list[dict[str, Any]] = []
        for line in lines:
            cleaned = line.strip()
            if not cleaned:
                continue
            try:
                parsed.append(json.loads(cleaned))
            except json.JSONDecodeError:
                continue

        return parsed[-limit:]

    def apply_signal_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        signal = payload.get("signal", {})
        market = payload.get("market", {})
        sentiment = payload.get("sentiment", {})
        risk = signal.get("risk_management", {})

        symbol = self._normalize_symbol(signal.get("symbol") or market.get("symbol"))
        action = str(signal.get("action", "HOLD")).upper().strip()
        market_price = self._as_float(signal.get("price") or market.get("price"), 0.0)

        state = self._load_state()
        now = self._now_iso()

        if not symbol:
            return {
                "status": "skipped",
                "reason": "Missing symbol in payload.",
                "paper": self._build_state_summary(state),
            }

        if market_price <= 0:
            return {
                "status": "skipped",
                "symbol": symbol,
                "action": action,
                "reason": "Missing or invalid market price.",
                "paper": self._build_state_summary(state),
            }

        positions = state["positions"]
        existing = positions.get(symbol)
        if existing:
            existing["last_price"] = market_price

        guardrails = self._ensure_daily_guardrails(state)
        drawdown_pct = self._drawdown_pct(
            self._as_float(guardrails.get("start_equity_usdt"), self.starting_cash_usdt),
            self._state_equity(state),
        )
        if drawdown_pct >= self.max_daily_drawdown_pct:
            guardrails["hard_stop_active"] = True
            if not str(guardrails.get("hard_stop_reason", "")).strip():
                guardrails["hard_stop_reason"] = (
                    f"Daily drawdown {drawdown_pct:.2f}% reached limit {self.max_daily_drawdown_pct:.2f}%."
                )

        if action not in {"BUY", "SELL"}:
            state["updated_at"] = now
            self._save_state(state)
            return {
                "status": "skipped",
                "symbol": symbol,
                "action": action,
                "reason": "Action is HOLD or unsupported for execution.",
                "paper": self._build_state_summary(state),
            }

        target_notional = max(self._as_float(risk.get("position_size_usdt"), 0.0), 0.0)
        signal_confidence = self._as_float(signal.get("confidence"), 0.0)
        sentiment_score = self._as_float(sentiment.get("score"), 0.0)
        model_source = str(sentiment.get("model_source", "unknown"))

        fee_rate = self.fee_bps / 10000.0
        slippage_rate = self.slippage_bps / 10000.0

        if action == "BUY":
            trade_allowed = bool(risk.get("trade_allowed", True))
            if not trade_allowed:
                state["updated_at"] = now
                self._save_state(state)
                return {
                    "status": "skipped",
                    "symbol": symbol,
                    "action": action,
                    "reason": "Risk gate blocked entry.",
                    "paper": self._build_state_summary(state),
                }

            if bool(guardrails.get("hard_stop_active", False)):
                state["updated_at"] = now
                self._save_state(state)
                stop_reason = str(guardrails.get("hard_stop_reason", "")).strip() or "Daily hard stop is active."
                return {
                    "status": "skipped",
                    "symbol": symbol,
                    "action": action,
                    "reason": stop_reason,
                    "paper": self._build_state_summary(state),
                }

            trades_executed = int(guardrails.get("trades_executed", 0) or 0)
            if trades_executed >= self.max_trades_per_day:
                state["updated_at"] = now
                self._save_state(state)
                return {
                    "status": "skipped",
                    "symbol": symbol,
                    "action": action,
                    "reason": (
                        f"Daily trade limit reached ({trades_executed}/{self.max_trades_per_day}). "
                        "New BUY entries are blocked until next UTC day."
                    ),
                    "paper": self._build_state_summary(state),
                }

            execution_price = market_price * (1.0 + slippage_rate)
            cash_usdt = max(self._as_float(state.get("cash_usdt"), 0.0), 0.0)
            max_notional = cash_usdt / (1.0 + fee_rate) if fee_rate >= 0.0 else cash_usdt
            desired_notional = target_notional if target_notional > 0 else max_notional
            notional_usdt = min(desired_notional, max_notional)

            if notional_usdt < self.min_notional_usdt:
                state["updated_at"] = now
                self._save_state(state)
                return {
                    "status": "skipped",
                    "symbol": symbol,
                    "action": action,
                    "reason": "Insufficient cash for minimum notional.",
                    "paper": self._build_state_summary(state),
                }

            quantity = notional_usdt / execution_price
            fee_usdt = notional_usdt * fee_rate
            total_cost_usdt = notional_usdt + fee_usdt

            state["cash_usdt"] = cash_usdt - total_cost_usdt
            state["fees_paid_usdt"] = self._as_float(state.get("fees_paid_usdt"), 0.0) + fee_usdt

            if existing:
                prev_qty = self._as_float(existing.get("quantity"), 0.0)
                prev_avg = self._as_float(existing.get("avg_price"), execution_price)
                new_qty = prev_qty + quantity
                new_avg = ((prev_qty * prev_avg) + (quantity * execution_price)) / max(new_qty, 1e-12)
                existing["quantity"] = new_qty
                existing["avg_price"] = new_avg
                existing["last_price"] = market_price
            else:
                positions[symbol] = {
                    "quantity": quantity,
                    "avg_price": execution_price,
                    "last_price": market_price,
                    "opened_at": now,
                }

            trade = {
                "timestamp": now,
                "symbol": symbol,
                "side": "BUY",
                "quantity": quantity,
                "execution_price": execution_price,
                "notional_usdt": notional_usdt,
                "fee_usdt": fee_usdt,
                "cash_flow_usdt": -total_cost_usdt,
                "realized_pnl_usdt": 0.0,
                "signal_confidence": signal_confidence,
                "sentiment_score": sentiment_score,
                "model_source": model_source,
            }

        else:
            position = positions.get(symbol)
            if not position or self._as_float(position.get("quantity"), 0.0) <= 0.0:
                state["updated_at"] = now
                self._save_state(state)
                return {
                    "status": "skipped",
                    "symbol": symbol,
                    "action": action,
                    "reason": "No open position to close.",
                    "paper": self._build_state_summary(state),
                }

            execution_price = market_price * (1.0 - slippage_rate)
            quantity_open = self._as_float(position.get("quantity"), 0.0)
            quantity_to_sell = quantity_open
            if target_notional > 0:
                quantity_to_sell = min(quantity_open, target_notional / max(execution_price, 1e-12))

            quantity_to_sell = max(quantity_to_sell, 0.0)
            if quantity_to_sell <= 0.0:
                state["updated_at"] = now
                self._save_state(state)
                return {
                    "status": "skipped",
                    "symbol": symbol,
                    "action": action,
                    "reason": "Sell quantity resolved to zero.",
                    "paper": self._build_state_summary(state),
                }

            notional_usdt = quantity_to_sell * execution_price
            if notional_usdt < self.min_notional_usdt and quantity_to_sell < quantity_open:
                quantity_to_sell = quantity_open
                notional_usdt = quantity_to_sell * execution_price

            fee_usdt = notional_usdt * fee_rate
            net_proceeds_usdt = notional_usdt - fee_usdt
            avg_price = self._as_float(position.get("avg_price"), execution_price)
            cost_basis_usdt = quantity_to_sell * avg_price
            realized_pnl_usdt = net_proceeds_usdt - cost_basis_usdt

            state["cash_usdt"] = self._as_float(state.get("cash_usdt"), 0.0) + net_proceeds_usdt
            state["realized_pnl_usdt"] = self._as_float(state.get("realized_pnl_usdt"), 0.0) + realized_pnl_usdt
            state["fees_paid_usdt"] = self._as_float(state.get("fees_paid_usdt"), 0.0) + fee_usdt

            remaining_qty = quantity_open - quantity_to_sell
            if remaining_qty <= 1e-12:
                positions.pop(symbol, None)
            else:
                position["quantity"] = remaining_qty
                position["last_price"] = market_price

            trade = {
                "timestamp": now,
                "symbol": symbol,
                "side": "SELL",
                "quantity": quantity_to_sell,
                "execution_price": execution_price,
                "notional_usdt": notional_usdt,
                "fee_usdt": fee_usdt,
                "cash_flow_usdt": net_proceeds_usdt,
                "realized_pnl_usdt": realized_pnl_usdt,
                "signal_confidence": signal_confidence,
                "sentiment_score": sentiment_score,
                "model_source": model_source,
            }

        state["updated_at"] = now
        guardrails["trades_executed"] = int(guardrails.get("trades_executed", 0) or 0) + 1
        self._save_state(state)
        self._append_trade(trade)

        return {
            "status": "executed",
            "symbol": symbol,
            "action": action,
            "trade": trade,
            "paper": self._build_state_summary(state),
        }

    def _append_trade(self, trade: dict[str, Any]) -> None:
        self.trades_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trades_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(trade, ensure_ascii=True) + "\n")

    def _default_state(self) -> dict[str, Any]:
        start_of_day_equity = self.starting_cash_usdt
        return {
            "starting_cash_usdt": self.starting_cash_usdt,
            "cash_usdt": self.starting_cash_usdt,
            "realized_pnl_usdt": 0.0,
            "fees_paid_usdt": 0.0,
            "positions": {},
            "daily_guardrails": {
                "date": self._utc_date(),
                "trades_executed": 0,
                "start_equity_usdt": start_of_day_equity,
                "hard_stop_active": False,
                "hard_stop_reason": "",
            },
            "updated_at": self._now_iso(),
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()

        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return self._default_state()

        state = self._default_state()
        state["starting_cash_usdt"] = self._as_float(raw.get("starting_cash_usdt"), self.starting_cash_usdt)
        state["cash_usdt"] = self._as_float(raw.get("cash_usdt"), state["starting_cash_usdt"])
        state["realized_pnl_usdt"] = self._as_float(raw.get("realized_pnl_usdt"), 0.0)
        state["fees_paid_usdt"] = self._as_float(raw.get("fees_paid_usdt"), 0.0)
        state["updated_at"] = str(raw.get("updated_at") or self._now_iso())

        positions: dict[str, Any] = {}
        raw_positions = raw.get("positions") if isinstance(raw.get("positions"), dict) else {}
        for key, value in raw_positions.items():
            symbol = self._normalize_symbol(key)
            if not symbol or not isinstance(value, dict):
                continue

            quantity = max(self._as_float(value.get("quantity"), 0.0), 0.0)
            avg_price = max(self._as_float(value.get("avg_price"), 0.0), 0.0)
            last_price = max(self._as_float(value.get("last_price"), avg_price), 0.0)
            opened_at = str(value.get("opened_at") or self._now_iso())

            if quantity <= 0.0 or avg_price <= 0.0:
                continue

            positions[symbol] = {
                "quantity": quantity,
                "avg_price": avg_price,
                "last_price": last_price if last_price > 0 else avg_price,
                "opened_at": opened_at,
            }

        state["positions"] = positions
        raw_guardrails = raw.get("daily_guardrails") if isinstance(raw.get("daily_guardrails"), dict) else {}
        state["daily_guardrails"] = {
            "date": str(raw_guardrails.get("date") or self._utc_date()),
            "trades_executed": max(int(raw_guardrails.get("trades_executed", 0) or 0), 0),
            "start_equity_usdt": max(
                self._as_float(raw_guardrails.get("start_equity_usdt"), self._state_equity(state)),
                1.0,
            ),
            "hard_stop_active": bool(raw_guardrails.get("hard_stop_active", False)),
            "hard_stop_reason": str(raw_guardrails.get("hard_stop_reason") or ""),
        }

        self._ensure_daily_guardrails(state)
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")

    def _build_state_summary(self, state: dict[str, Any]) -> dict[str, Any]:
        cash_usdt = self._as_float(state.get("cash_usdt"), 0.0)
        starting_cash_usdt = self._as_float(state.get("starting_cash_usdt"), self.starting_cash_usdt)
        realized_pnl_usdt = self._as_float(state.get("realized_pnl_usdt"), 0.0)
        fees_paid_usdt = self._as_float(state.get("fees_paid_usdt"), 0.0)

        positions_payload: list[dict[str, Any]] = []
        total_market_value = 0.0
        total_unrealized_pnl = 0.0

        raw_positions = state.get("positions") if isinstance(state.get("positions"), dict) else {}
        for symbol in sorted(raw_positions):
            pos = raw_positions[symbol]
            quantity = self._as_float(pos.get("quantity"), 0.0)
            avg_price = self._as_float(pos.get("avg_price"), 0.0)
            mark_price = self._as_float(pos.get("last_price"), avg_price)
            opened_at = str(pos.get("opened_at") or "")

            if quantity <= 0.0 or avg_price <= 0.0:
                continue

            market_value_usdt = quantity * mark_price
            cost_basis_usdt = quantity * avg_price
            unrealized_pnl_usdt = market_value_usdt - cost_basis_usdt
            unrealized_pnl_pct = (unrealized_pnl_usdt / cost_basis_usdt * 100.0) if cost_basis_usdt > 0 else 0.0

            total_market_value += market_value_usdt
            total_unrealized_pnl += unrealized_pnl_usdt

            positions_payload.append(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "avg_price": avg_price,
                    "mark_price": mark_price,
                    "market_value_usdt": market_value_usdt,
                    "cost_basis_usdt": cost_basis_usdt,
                    "unrealized_pnl_usdt": unrealized_pnl_usdt,
                    "unrealized_pnl_pct": unrealized_pnl_pct,
                    "opened_at": opened_at,
                }
            )

        equity_usdt = cash_usdt + total_market_value
        total_pnl_usdt = equity_usdt - starting_cash_usdt
        guardrails = self._ensure_daily_guardrails(state)
        start_equity = max(self._as_float(guardrails.get("start_equity_usdt"), equity_usdt), 1.0)
        drawdown_pct = self._drawdown_pct(start_equity, equity_usdt)
        hard_stop_active = bool(guardrails.get("hard_stop_active", False)) or drawdown_pct >= self.max_daily_drawdown_pct

        daily_guardrails = {
            "date": str(guardrails.get("date") or self._utc_date()),
            "trades_executed": int(guardrails.get("trades_executed", 0) or 0),
            "max_trades_per_day": self.max_trades_per_day,
            "start_equity_usdt": start_equity,
            "drawdown_pct": drawdown_pct,
            "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
            "hard_stop_active": hard_stop_active,
            "hard_stop_reason": str(guardrails.get("hard_stop_reason") or ""),
        }

        return {
            "starting_cash_usdt": starting_cash_usdt,
            "cash_usdt": cash_usdt,
            "equity_usdt": equity_usdt,
            "realized_pnl_usdt": realized_pnl_usdt,
            "unrealized_pnl_usdt": total_unrealized_pnl,
            "fees_paid_usdt": fees_paid_usdt,
            "total_pnl_usdt": total_pnl_usdt,
            "positions_count": len(positions_payload),
            "positions": positions_payload,
            "daily_guardrails": daily_guardrails,
            "updated_at": str(state.get("updated_at") or self._now_iso()),
        }

    def _ensure_daily_guardrails(self, state: dict[str, Any]) -> dict[str, Any]:
        today = self._utc_date()
        current_equity = self._state_equity(state)
        raw = state.get("daily_guardrails") if isinstance(state.get("daily_guardrails"), dict) else {}

        raw_date = str(raw.get("date") or "")
        if raw_date != today:
            daily = {
                "date": today,
                "trades_executed": 0,
                "start_equity_usdt": max(current_equity, 1.0),
                "hard_stop_active": False,
                "hard_stop_reason": "",
            }
            state["daily_guardrails"] = daily
            return daily

        daily = {
            "date": today,
            "trades_executed": max(int(raw.get("trades_executed", 0) or 0), 0),
            "start_equity_usdt": max(self._as_float(raw.get("start_equity_usdt"), current_equity), 1.0),
            "hard_stop_active": bool(raw.get("hard_stop_active", False)),
            "hard_stop_reason": str(raw.get("hard_stop_reason") or ""),
        }

        state["daily_guardrails"] = daily
        return daily

    @staticmethod
    def _drawdown_pct(start_equity_usdt: float, current_equity_usdt: float) -> float:
        safe_start = max(start_equity_usdt, 1.0)
        drop = max(safe_start - current_equity_usdt, 0.0)
        return (drop / safe_start) * 100.0

    def _state_equity(self, state: dict[str, Any]) -> float:
        cash_usdt = self._as_float(state.get("cash_usdt"), 0.0)
        total_market_value = 0.0
        positions = state.get("positions") if isinstance(state.get("positions"), dict) else {}
        for pos in positions.values():
            if not isinstance(pos, dict):
                continue
            quantity = max(self._as_float(pos.get("quantity"), 0.0), 0.0)
            mark_price = max(self._as_float(pos.get("last_price"), self._as_float(pos.get("avg_price"), 0.0)), 0.0)
            total_market_value += quantity * mark_price

        return cash_usdt + total_market_value

    @staticmethod
    def _normalize_symbol(value: object) -> str:
        raw = str(value or "").upper().strip()
        return "".join(ch for ch in raw if ch.isalnum())

    @staticmethod
    def _as_float(value: object, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _now_iso() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat()

    @staticmethod
    def _utc_date() -> str:
        return dt.datetime.now(dt.timezone.utc).date().isoformat()
