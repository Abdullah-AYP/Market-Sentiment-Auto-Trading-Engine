from __future__ import annotations

import datetime as dt

from .models import MarketSnapshot, SentimentResult, TradingSignal


class DecisionTreeStrategy:
    def __init__(
        self,
        bullish_threshold: float = 0.22,
        bearish_threshold: float = -0.22,
        min_sentiment_confidence: float = 0.45,
        neutral_band: float = 0.08,
        account_equity_usdt: float = 1000.0,
        risk_per_trade_pct: float = 1.0,
        base_position_size_pct: float = 10.0,
        min_position_size_pct: float = 2.0,
        max_position_size_pct: float = 20.0,
        max_volatility_24h_pct: float = 12.0,
        stop_loss_min_pct: float = 1.0,
        stop_loss_max_pct: float = 4.0,
        take_profit_rr: float = 2.0,
        max_daily_loss_pct: float = 3.0,
        daily_loss_used_pct: float = 0.0,
        momentum_override_pct: float = 1.2,
        min_trade_confidence: float = 0.52,
    ) -> None:
        self.bullish_threshold = bullish_threshold
        self.bearish_threshold = bearish_threshold
        self.min_sentiment_confidence = min_sentiment_confidence
        self.neutral_band = neutral_band
        self.account_equity_usdt = max(account_equity_usdt, 1.0)
        self.risk_per_trade_pct = self._clamp(risk_per_trade_pct, 0.05, 10.0)
        self.base_position_size_pct = self._clamp(base_position_size_pct, 0.1, 100.0)
        self.min_position_size_pct = self._clamp(min_position_size_pct, 0.0, 100.0)
        self.max_position_size_pct = self._clamp(max_position_size_pct, 0.0, 100.0)
        self.max_volatility_24h_pct = self._clamp(max_volatility_24h_pct, 0.5, 100.0)
        self.stop_loss_min_pct = self._clamp(stop_loss_min_pct, 0.1, 20.0)
        self.stop_loss_max_pct = self._clamp(stop_loss_max_pct, self.stop_loss_min_pct, 30.0)
        self.take_profit_rr = self._clamp(take_profit_rr, 0.5, 10.0)
        self.max_daily_loss_pct = self._clamp(max_daily_loss_pct, 0.1, 100.0)
        self.daily_loss_used_pct = self._clamp(daily_loss_used_pct, 0.0, 100.0)
        self.momentum_override_pct = self._clamp(momentum_override_pct, 0.1, 20.0)
        self.min_trade_confidence = self._clamp(min_trade_confidence, 0.0, 1.0)

    def evaluate(self, sentiment: SentimentResult, market: MarketSnapshot) -> TradingSignal:
        reasons: list[str] = []
        normalized_momentum = self._clamp(market.change_percent_24h / 12.0, -1.0, 1.0)
        composite_score = (0.8 * sentiment.score) + (0.2 * normalized_momentum)
        adaptive_shift = self._clamp((sentiment.confidence - 0.5) * 0.14, -0.07, 0.07)
        bullish_threshold = self.bullish_threshold - adaptive_shift
        bearish_threshold = self.bearish_threshold + adaptive_shift

        reasons.append(
            f"Sentiment score={sentiment.score:.3f}, confidence={sentiment.confidence:.3f}, "
            f"24h change={market.change_percent_24h:.2f}%"
        )

        if sentiment.confidence < self.min_sentiment_confidence:
            action = "HOLD"
            reasons.append("Confidence below minimum threshold; avoid directional trade.")
        elif sentiment.score >= 0.55 and market.change_percent_24h >= self.momentum_override_pct:
            action = "BUY"
            reasons.append("Momentum override: strong sentiment with supportive price acceleration.")
        elif sentiment.score <= -0.55 and market.change_percent_24h <= -self.momentum_override_pct:
            action = "SELL"
            reasons.append("Momentum override: strong negative sentiment with downside acceleration.")
        elif composite_score >= bullish_threshold and market.change_percent_24h > -7.0:
            action = "BUY"
            reasons.append("Bullish composite score with acceptable downside risk filter.")
        elif composite_score <= bearish_threshold and market.change_percent_24h < 7.0:
            action = "SELL"
            reasons.append("Bearish composite score with acceptable upside risk filter.")
        elif abs(composite_score) <= self.neutral_band:
            action = "HOLD"
            reasons.append("Signal in neutral zone; no strong edge.")
        else:
            action = "HOLD"
            reasons.append("Conflicting conditions; defaulting to HOLD.")

        confidence = self._clamp((0.65 * sentiment.confidence) + (0.35 * abs(composite_score)), 0.1, 0.99)
        risk_management = self._build_risk_plan(
            action,
            confidence,
            market,
            sentiment_confidence=sentiment.confidence,
        )

        if action in {"BUY", "SELL"} and not risk_management["trade_allowed"]:
            action = "HOLD"
            reasons.append("Risk rules blocked entry; downgraded to HOLD.")

        if risk_management["rules_triggered"]:
            reasons.append("Risk summary: " + "; ".join(risk_management["rules_triggered"]))

        return TradingSignal(
            symbol=market.symbol,
            action=action,
            confidence=confidence,
            reasons=reasons,
            risk_management=risk_management,
            price=market.price,
            timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
        )

    def _build_risk_plan(
        self,
        action: str,
        signal_confidence: float,
        market: MarketSnapshot,
        sentiment_confidence: float,
    ) -> dict[str, object]:
        observed_volatility = abs(market.change_percent_24h)
        rules_triggered: list[str] = []
        trade_allowed = action in {"BUY", "SELL"}
        position_size_pct = 0.0
        position_size_usdt = 0.0
        stop_loss_pct = 0.0
        take_profit_pct = 0.0
        stop_loss_price: float | None = None
        take_profit_price: float | None = None
        max_risk_usdt = self.account_equity_usdt * (self.risk_per_trade_pct / 100.0)
        estimated_risk_usdt = 0.0
        gate_confidence = max(signal_confidence, sentiment_confidence * 0.92)

        if not trade_allowed:
            rules_triggered.append("No directional action from strategy.")

        if gate_confidence < self.min_trade_confidence:
            trade_allowed = False
            rules_triggered.append(
                f"Gate confidence {gate_confidence:.2f} below minimum trade confidence "
                f"{self.min_trade_confidence:.2f}."
            )

        if observed_volatility > self.max_volatility_24h_pct:
            trade_allowed = False
            rules_triggered.append(
                f"24h volatility {observed_volatility:.2f}% exceeds limit {self.max_volatility_24h_pct:.2f}%."
            )

        if self.daily_loss_used_pct >= self.max_daily_loss_pct:
            trade_allowed = False
            rules_triggered.append(
                f"Daily loss used {self.daily_loss_used_pct:.2f}% reached max {self.max_daily_loss_pct:.2f}%."
            )

        if action in {"BUY", "SELL"} and trade_allowed:
            volatility_factor = self._clamp(
                1.0 - (observed_volatility / self.max_volatility_24h_pct),
                0.25,
                1.0,
            )
            proposed_size_pct = self.base_position_size_pct * signal_confidence * volatility_factor
            position_size_pct = self._clamp(
                proposed_size_pct,
                self.min_position_size_pct,
                self.max_position_size_pct,
            )

            raw_stop_loss_pct = 1.0 + (observed_volatility * 0.12) + ((1.0 - signal_confidence) * 1.5)
            stop_loss_pct = self._clamp(raw_stop_loss_pct, self.stop_loss_min_pct, self.stop_loss_max_pct)
            take_profit_pct = stop_loss_pct * self.take_profit_rr

            position_size_usdt = self.account_equity_usdt * (position_size_pct / 100.0)
            estimated_risk_usdt = position_size_usdt * (stop_loss_pct / 100.0)

            if estimated_risk_usdt > max_risk_usdt and estimated_risk_usdt > 0:
                scale = max_risk_usdt / estimated_risk_usdt
                position_size_pct *= scale
                if position_size_pct < self.min_position_size_pct:
                    trade_allowed = False
                    rules_triggered.append(
                        "Risk budget would force position below minimum size; trade blocked."
                    )
                    position_size_pct = 0.0
                    position_size_usdt = 0.0
                    stop_loss_pct = 0.0
                    take_profit_pct = 0.0
                    estimated_risk_usdt = 0.0
                else:
                    position_size_usdt = self.account_equity_usdt * (position_size_pct / 100.0)
                    estimated_risk_usdt = position_size_usdt * (stop_loss_pct / 100.0)
                    rules_triggered.append("Position size reduced to satisfy max risk per trade.")

            if trade_allowed:
                if action == "BUY":
                    stop_loss_price = market.price * (1 - (stop_loss_pct / 100.0))
                    take_profit_price = market.price * (1 + (take_profit_pct / 100.0))
                else:
                    stop_loss_price = market.price * (1 + (stop_loss_pct / 100.0))
                    take_profit_price = market.price * (1 - (take_profit_pct / 100.0))

        return {
            "trade_allowed": trade_allowed,
            "action_considered": action,
            "gate_confidence": round(gate_confidence, 4),
            "account_equity_usdt": round(self.account_equity_usdt, 4),
            "risk_per_trade_pct": round(self.risk_per_trade_pct, 4),
            "max_risk_usdt": round(max_risk_usdt, 4),
            "position_size_pct": round(position_size_pct, 4),
            "position_size_usdt": round(position_size_usdt, 4),
            "estimated_risk_usdt": round(estimated_risk_usdt, 4),
            "stop_loss_pct": round(stop_loss_pct, 4),
            "take_profit_pct": round(take_profit_pct, 4),
            "stop_loss_price": round(stop_loss_price, 8) if stop_loss_price is not None else None,
            "take_profit_price": round(take_profit_price, 8) if take_profit_price is not None else None,
            "reward_to_risk": round(self.take_profit_rr, 4),
            "observed_volatility_24h_pct": round(observed_volatility, 4),
            "max_volatility_24h_pct": round(self.max_volatility_24h_pct, 4),
            "daily_loss_used_pct": round(self.daily_loss_used_pct, 4),
            "max_daily_loss_pct": round(self.max_daily_loss_pct, 4),
            "rules_triggered": rules_triggered,
        }

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
