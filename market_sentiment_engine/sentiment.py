from __future__ import annotations

import json
import logging
from typing import Iterable

from openai import OpenAI

from .models import MarketSnapshot, NewsItem, SentimentResult


LOGGER = logging.getLogger(__name__)


GITHUB_TOKEN_PREFIXES = (
    "github_pat_",
    "ghp_",
    "gho_",
    "ghu_",
    "ghs_",
    "ghr_",
)


class OpenAISentimentAnalyzer:
    def __init__(self, api_key: str | None, model: str, base_url: str | None = None) -> None:
        self.model = model
        self.base_url = base_url.strip() if base_url else None
        self.client: OpenAI | None = None
        self.disabled_reason: str | None = None

        normalized_key = self._normalize_api_key(api_key)
        if not normalized_key:
            return

        if self._looks_like_github_token(normalized_key) and not self.base_url:
            self.disabled_reason = (
                "GitHub token detected in OPENAI_API_KEY, but OPENAI_BASE_URL is not set. "
                "Use an OpenAI key from platform.openai.com, or configure OPENAI_BASE_URL "
                "for your provider's OpenAI-compatible endpoint."
            )
            LOGGER.warning(self.disabled_reason)
            return

        try:
            client_kwargs: dict[str, str] = {"api_key": normalized_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self.client = OpenAI(**client_kwargs)
        except Exception as exc:
            self.disabled_reason = f"Failed to initialize OpenAI client: {exc}"
            LOGGER.warning(self.disabled_reason)

    def analyze(self, news_items: list[NewsItem], market: MarketSnapshot) -> SentimentResult:
        if not news_items:
            return SentimentResult(
                score=0.0,
                confidence=0.2,
                rationale="No headlines were available for this cycle.",
                model_source="fallback",
            )

        if not self.client:
            fallback_result = self._lexicon_fallback(news_items)
            if self.disabled_reason:
                return SentimentResult(
                    score=fallback_result.score,
                    confidence=fallback_result.confidence,
                    rationale=f"{fallback_result.rationale} {self.disabled_reason}",
                    model_source="fallback",
                )
            return fallback_result

        headlines_text = self._format_headlines(news_items)
        prompt = (
            "Analyze sentiment for short-term spot trading.\n"
            f"Symbol: {market.symbol}\n"
            f"Price: {market.price}\n"
            f"24h Change: {market.change_percent_24h}%\n\n"
            "Headlines:\n"
            f"{headlines_text}\n\n"
            "Return STRICT JSON with keys score, confidence, rationale where:\n"
            "- score is a float from -1.0 to +1.0\n"
            "- confidence is a float from 0.0 to 1.0\n"
            "- rationale is brief and factual"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "You are a careful and conservative crypto sentiment classifier.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or "{}"
            payload = json.loads(content)

            score = self._clamp(float(payload.get("score", 0.0)), -1.0, 1.0)
            confidence = self._clamp(float(payload.get("confidence", 0.5)), 0.0, 1.0)
            rationale = str(payload.get("rationale", "No rationale provided.")).strip()

            return SentimentResult(
                score=score,
                confidence=confidence,
                rationale=rationale,
                model_source=self.model,
            )
        except Exception as exc:
            LOGGER.warning("Sentiment API call failed, switching to fallback model: %s", exc)
            return self._lexicon_fallback(news_items)

    @staticmethod
    def _normalize_api_key(api_key: str | None) -> str | None:
        if not api_key:
            return None
        normalized = api_key.strip().strip('"').strip("'")
        if normalized.lower().startswith("bearer "):
            normalized = normalized[7:].strip()
        return normalized or None

    @staticmethod
    def _looks_like_github_token(api_key: str) -> bool:
        lowered = api_key.lower()
        return lowered.startswith(GITHUB_TOKEN_PREFIXES)

    @staticmethod
    def _format_headlines(news_items: Iterable[NewsItem]) -> str:
        return "\n".join(f"- {item.title}" for item in news_items)

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    def _lexicon_fallback(self, news_items: list[NewsItem]) -> SentimentResult:
        positive_words = {
            "surge",
            "rally",
            "gain",
            "bullish",
            "breakout",
            "approval",
            "adoption",
            "partnership",
            "record",
            "upside",
        }
        negative_words = {
            "drop",
            "plunge",
            "bearish",
            "lawsuit",
            "crash",
            "hack",
            "selloff",
            "downside",
            "ban",
            "risk",
        }

        positive_hits = 0
        negative_hits = 0

        for item in news_items:
            line = item.title.lower()
            positive_hits += sum(1 for word in positive_words if word in line)
            negative_hits += sum(1 for word in negative_words if word in line)

        total_hits = positive_hits + negative_hits
        if total_hits == 0:
            return SentimentResult(
                score=0.0,
                confidence=0.3,
                rationale="No directional keywords detected in headlines.",
                model_source="fallback",
            )

        score = (positive_hits - negative_hits) / total_hits
        confidence = self._clamp(0.35 + (min(total_hits, 15) / 30), 0.0, 0.75)
        rationale = (
            f"Fallback sentiment from keyword counts: {positive_hits} positive vs "
            f"{negative_hits} negative matches."
        )

        return SentimentResult(
            score=self._clamp(score, -1.0, 1.0),
            confidence=confidence,
            rationale=rationale,
            model_source="fallback",
        )
