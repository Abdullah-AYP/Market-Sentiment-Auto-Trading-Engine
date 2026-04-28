from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings
from .decision import DecisionTreeStrategy
from .models import MarketSnapshot, SentimentResult


@dataclass(frozen=True)
class SignalObservation:
    symbol: str
    market: MarketSnapshot
    sentiment: SentimentResult


@dataclass(frozen=True)
class StrategyParameters:
    bullish_threshold: float
    bearish_threshold: float
    min_sentiment_confidence: float
    neutral_band: float
    momentum_override_pct: float
    min_trade_confidence: float


@dataclass(frozen=True)
class SearchConfig:
    beam_width: int = 8
    depth: int = 10
    hold_penalty: float = 0.35
    trade_cost_pct: float = 0.08
    move_threshold_pct: float = 0.12


@dataclass(frozen=True)
class StrategyScore:
    parameters: StrategyParameters
    score: float
    samples: int
    avg_reward_pct: float
    total_reward_pct: float
    directional_accuracy: float
    exact_accuracy: float
    buy_count: int
    sell_count: int
    hold_count: int


PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "bullish_threshold": (0.08, 0.45),
    "bearish_threshold": (-0.45, -0.08),
    "min_sentiment_confidence": (0.20, 0.95),
    "neutral_band": (0.02, 0.22),
    "momentum_override_pct": (0.20, 4.00),
    "min_trade_confidence": (0.20, 0.95),
}

PARAM_STEPS: dict[str, float] = {
    "bullish_threshold": 0.01,
    "bearish_threshold": 0.01,
    "min_sentiment_confidence": 0.02,
    "neutral_band": 0.01,
    "momentum_override_pct": 0.10,
    "min_trade_confidence": 0.02,
}


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize_symbol(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    return raw.strip().upper()


def classify_future_move(change_pct: float, move_threshold_pct: float) -> str:
    if change_pct > move_threshold_pct:
        return "BUY"
    if change_pct < -move_threshold_pct:
        return "SELL"
    return "HOLD"


def parameters_from_settings(settings: Settings) -> StrategyParameters:
    return StrategyParameters(
        bullish_threshold=settings.bullish_threshold,
        bearish_threshold=settings.bearish_threshold,
        min_sentiment_confidence=settings.min_sentiment_confidence,
        neutral_band=settings.neutral_band,
        momentum_override_pct=settings.momentum_override_pct,
        min_trade_confidence=settings.min_trade_confidence,
    )


def _is_valid_parameters(params: StrategyParameters) -> bool:
    if params.bearish_threshold >= -0.05:
        return False
    if params.bullish_threshold <= 0.05:
        return False
    if params.bearish_threshold >= params.bullish_threshold - 0.05:
        return False
    if params.neutral_band >= 0.5:
        return False
    if params.min_trade_confidence < params.min_sentiment_confidence * 0.5:
        return False
    return True


def _parameter_neighbors(params: StrategyParameters) -> list[StrategyParameters]:
    neighbors: list[StrategyParameters] = []
    as_map = asdict(params)

    for name, step in PARAM_STEPS.items():
        minimum, maximum = PARAM_BOUNDS[name]
        for direction in (-1.0, 1.0):
            candidate_map = dict(as_map)
            current = float(candidate_map[name])
            updated = round(_clamp(current + (direction * step), minimum, maximum), 6)
            if updated == current:
                continue
            candidate_map[name] = updated
            candidate = StrategyParameters(**candidate_map)
            if _is_valid_parameters(candidate):
                neighbors.append(candidate)

    deduped: dict[StrategyParameters, None] = {}
    for item in neighbors:
        deduped[item] = None
    return list(deduped.keys())


def load_observations_from_signals(signals_path: Path) -> dict[str, list[SignalObservation]]:
    observations: dict[str, list[SignalObservation]] = {}
    if not signals_path.exists():
        return observations

    for raw_line in signals_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        market_raw = payload.get("market") if isinstance(payload.get("market"), dict) else {}
        sentiment_raw = payload.get("sentiment") if isinstance(payload.get("sentiment"), dict) else {}
        signal_raw = payload.get("signal") if isinstance(payload.get("signal"), dict) else {}

        symbol = _normalize_symbol(
            market_raw.get("symbol")
            or signal_raw.get("symbol")
        )
        if not symbol:
            continue

        market = MarketSnapshot(
            symbol=symbol,
            price=_to_float(market_raw.get("price"), 0.0),
            change_percent_24h=_to_float(market_raw.get("change_percent_24h"), 0.0),
            volume_24h=_to_float(market_raw.get("volume_24h"), 0.0),
            timestamp=str(market_raw.get("timestamp") or signal_raw.get("timestamp") or ""),
        )
        if market.price <= 0:
            continue

        sentiment = SentimentResult(
            score=_to_float(sentiment_raw.get("score"), 0.0),
            confidence=_clamp(_to_float(sentiment_raw.get("confidence"), 0.0), 0.0, 1.0),
            rationale=str(sentiment_raw.get("rationale") or ""),
            model_source=str(sentiment_raw.get("model_source") or "unknown"),
        )

        obs = SignalObservation(symbol=symbol, market=market, sentiment=sentiment)
        observations.setdefault(symbol, []).append(obs)

    for symbol in observations:
        observations[symbol].sort(key=lambda item: item.market.timestamp)

    return observations


def build_transition_pairs(observations_by_symbol: dict[str, list[SignalObservation]]) -> list[tuple[SignalObservation, SignalObservation]]:
    pairs: list[tuple[SignalObservation, SignalObservation]] = []
    for series in observations_by_symbol.values():
        if len(series) < 2:
            continue
        for index in range(len(series) - 1):
            current = series[index]
            nxt = series[index + 1]
            if current.market.price > 0 and nxt.market.price > 0:
                pairs.append((current, nxt))
    return pairs


def evaluate_parameters(
    params: StrategyParameters,
    transitions: list[tuple[SignalObservation, SignalObservation]],
    settings: Settings,
    hold_penalty: float,
    trade_cost_pct: float,
    move_threshold_pct: float,
) -> StrategyScore:
    strategy = DecisionTreeStrategy(
        bullish_threshold=params.bullish_threshold,
        bearish_threshold=params.bearish_threshold,
        min_sentiment_confidence=params.min_sentiment_confidence,
        neutral_band=params.neutral_band,
        account_equity_usdt=settings.account_equity_usdt,
        risk_per_trade_pct=settings.risk_per_trade_pct,
        base_position_size_pct=settings.base_position_size_pct,
        min_position_size_pct=settings.min_position_size_pct,
        max_position_size_pct=settings.max_position_size_pct,
        max_volatility_24h_pct=settings.max_volatility_24h_pct,
        stop_loss_min_pct=settings.stop_loss_min_pct,
        stop_loss_max_pct=settings.stop_loss_max_pct,
        take_profit_rr=settings.take_profit_rr,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        daily_loss_used_pct=settings.daily_loss_used_pct,
        momentum_override_pct=params.momentum_override_pct,
        min_trade_confidence=params.min_trade_confidence,
    )

    buy_count = 0
    sell_count = 0
    hold_count = 0
    directional_hits = 0
    directional_total = 0
    exact_hits = 0
    total_reward_pct = 0.0

    for current, nxt in transitions:
        signal = strategy.evaluate(current.sentiment, current.market)
        action = signal.action.upper()
        if action not in {"BUY", "SELL", "HOLD"}:
            action = "HOLD"

        if action == "BUY":
            buy_count += 1
        elif action == "SELL":
            sell_count += 1
        else:
            hold_count += 1

        price_now = max(current.market.price, 1e-12)
        change_pct = ((nxt.market.price / price_now) - 1.0) * 100.0

        if action == "BUY":
            reward_pct = change_pct - trade_cost_pct
        elif action == "SELL":
            reward_pct = -change_pct - trade_cost_pct
        else:
            reward_pct = -abs(change_pct) * hold_penalty

        total_reward_pct += reward_pct

        target = classify_future_move(change_pct, move_threshold_pct)
        if action == target:
            exact_hits += 1

        if target in {"BUY", "SELL"}:
            directional_total += 1
            if action == target:
                directional_hits += 1

    samples = len(transitions)
    if samples == 0:
        return StrategyScore(
            parameters=params,
            score=float("-inf"),
            samples=0,
            avg_reward_pct=0.0,
            total_reward_pct=0.0,
            directional_accuracy=0.0,
            exact_accuracy=0.0,
            buy_count=0,
            sell_count=0,
            hold_count=0,
        )

    avg_reward_pct = total_reward_pct / samples
    directional_accuracy = directional_hits / directional_total if directional_total else 0.0
    exact_accuracy = exact_hits / samples

    # Composite objective: reward first, then directional quality.
    score = avg_reward_pct + (0.15 * directional_accuracy) + (0.05 * exact_accuracy)

    return StrategyScore(
        parameters=params,
        score=score,
        samples=samples,
        avg_reward_pct=avg_reward_pct,
        total_reward_pct=total_reward_pct,
        directional_accuracy=directional_accuracy,
        exact_accuracy=exact_accuracy,
        buy_count=buy_count,
        sell_count=sell_count,
        hold_count=hold_count,
    )


def beam_search_optimize(
    transitions: list[tuple[SignalObservation, SignalObservation]],
    settings: Settings,
    config: SearchConfig,
) -> tuple[StrategyScore, list[StrategyScore]]:
    initial = parameters_from_settings(settings)
    if not _is_valid_parameters(initial):
        initial = StrategyParameters(
            bullish_threshold=0.22,
            bearish_threshold=-0.22,
            min_sentiment_confidence=0.45,
            neutral_band=0.08,
            momentum_override_pct=1.2,
            min_trade_confidence=0.52,
        )

    cache: dict[StrategyParameters, StrategyScore] = {}

    def score_params(params: StrategyParameters) -> StrategyScore:
        if params not in cache:
            cache[params] = evaluate_parameters(
                params=params,
                transitions=transitions,
                settings=settings,
                hold_penalty=config.hold_penalty,
                trade_cost_pct=config.trade_cost_pct,
                move_threshold_pct=config.move_threshold_pct,
            )
        return cache[params]

    beam: list[StrategyParameters] = [initial]
    best = score_params(initial)

    for _ in range(max(config.depth, 1)):
        candidate_params: dict[StrategyParameters, None] = {state: None for state in beam}
        for state in beam:
            for neighbor in _parameter_neighbors(state):
                candidate_params[neighbor] = None

        ranked = sorted(
            (score_params(params) for params in candidate_params),
            key=lambda item: item.score,
            reverse=True,
        )
        beam = [item.parameters for item in ranked[: max(1, config.beam_width)]]

        if ranked and ranked[0].score > best.score:
            best = ranked[0]

    leaderboard = sorted(cache.values(), key=lambda item: item.score, reverse=True)
    return best, leaderboard


def _format_env_overrides(params: StrategyParameters) -> str:
    return "\n".join(
        [
            f"BULLISH_THRESHOLD={params.bullish_threshold:.3f}",
            f"BEARISH_THRESHOLD={params.bearish_threshold:.3f}",
            f"MIN_SENTIMENT_CONFIDENCE={params.min_sentiment_confidence:.3f}",
            f"NEUTRAL_BAND={params.neutral_band:.3f}",
            f"MOMENTUM_OVERRIDE_PCT={params.momentum_override_pct:.3f}",
            f"MIN_TRADE_CONFIDENCE={params.min_trade_confidence:.3f}",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize strategy thresholds with local beam search.")
    parser.add_argument("--signals-path", default="signals/signals.jsonl", help="Path to signal history JSONL.")
    parser.add_argument("--beam-width", type=int, default=8, help="Beam width per iteration.")
    parser.add_argument("--depth", type=int, default=10, help="Search depth (iterations).")
    parser.add_argument("--hold-penalty", type=float, default=0.35, help="Penalty factor for HOLD.")
    parser.add_argument("--trade-cost-pct", type=float, default=0.08, help="Cost penalty per BUY/SELL decision.")
    parser.add_argument("--move-threshold-pct", type=float, default=0.12, help="Move threshold for classification metrics.")
    parser.add_argument("--top", type=int, default=5, help="Number of top candidates to print.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    signals_path = Path(args.signals_path)
    settings = Settings.from_env()

    observations = load_observations_from_signals(signals_path)
    transitions = build_transition_pairs(observations)

    if len(transitions) < 8:
        print(
            "Not enough transition samples for search. "
            f"Need >= 8, found {len(transitions)} from {signals_path}."
        )
        return 1

    config = SearchConfig(
        beam_width=max(1, args.beam_width),
        depth=max(1, args.depth),
        hold_penalty=max(0.0, args.hold_penalty),
        trade_cost_pct=max(0.0, args.trade_cost_pct),
        move_threshold_pct=max(0.0, args.move_threshold_pct),
    )

    best, leaderboard = beam_search_optimize(
        transitions=transitions,
        settings=settings,
        config=config,
    )

    top_n = max(1, args.top)
    top_items = leaderboard[:top_n]

    if args.json:
        payload = {
            "samples": len(transitions),
            "symbols": sorted(observations.keys()),
            "best": {
                "parameters": asdict(best.parameters),
                "score": best.score,
                "avg_reward_pct": best.avg_reward_pct,
                "directional_accuracy": best.directional_accuracy,
                "exact_accuracy": best.exact_accuracy,
                "buy_count": best.buy_count,
                "sell_count": best.sell_count,
                "hold_count": best.hold_count,
            },
            "leaderboard": [
                {
                    "parameters": asdict(item.parameters),
                    "score": item.score,
                    "avg_reward_pct": item.avg_reward_pct,
                    "directional_accuracy": item.directional_accuracy,
                    "exact_accuracy": item.exact_accuracy,
                }
                for item in top_items
            ],
            "env_overrides": asdict(best.parameters),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return 0

    print(f"Loaded {len(transitions)} transition samples across {len(observations)} symbols.")
    print("Best beam-search candidate:")
    print(
        "  score={:.6f} avg_reward_pct={:.6f} directional_accuracy={:.2%} exact_accuracy={:.2%}".format(
            best.score,
            best.avg_reward_pct,
            best.directional_accuracy,
            best.exact_accuracy,
        )
    )
    print(
        "  actions: BUY={} SELL={} HOLD={}".format(
            best.buy_count,
            best.sell_count,
            best.hold_count,
        )
    )
    print("Suggested .env overrides:")
    print(_format_env_overrides(best.parameters))

    print("\nTop candidates:")
    for idx, item in enumerate(top_items, start=1):
        params = item.parameters
        print(
            "  {}. score={:.6f} avg_reward={:.6f} dir_acc={:.2%} | "
            "BULL={:.3f} BEAR={:.3f} MIN_SENT={:.3f} NEUTRAL={:.3f} MOM={:.3f} MIN_TRADE={:.3f}".format(
                idx,
                item.score,
                item.avg_reward_pct,
                item.directional_accuracy,
                params.bullish_threshold,
                params.bearish_threshold,
                params.min_sentiment_confidence,
                params.neutral_band,
                params.momentum_override_pct,
                params.min_trade_confidence,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
