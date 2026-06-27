"""AI recommendation orchestrator with guaranteed rule-based fallback.

For each selected URL this builds structured facts, asks the provider for JSON,
validates it against the schema, and then forces url, bucket, and priority_score
back to the authoritative values so the AI can never change a score (requirement
1). Any failure at any step (no provider, unavailable provider, network error,
invalid JSON, failed validation) falls back to the rule-based recommendation, so
the function always returns valid records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from ppi.ai.facts import SYSTEM_PROMPT, build_facts, build_user_prompt
from ppi.ai.providers import Provider
from ppi.ai.schema import AiRecommendation
from ppi.reporting.recommendations import build_recommendation

# Cap on how many URLs are ever sent to a provider in one run. Keeps the request
# small and bounds cost and exposure, per the privacy rules.
MAX_AI_URLS = 25

_RISK_BY_BUCKET = {
    "Fix Now": "High",
    "Performance Fix": "Medium",
    "Quick Win": "Medium",
    "Refresh/Expand": "Medium",
    "Internal Link Push": "Low",
    "Authority Gap": "Medium",
    "Protect": "Low",
    "Merge/Prune": "Low",
    "Monitor": "Low",
}

# Map the rule-based owner phrasing onto the schema's allowed owner values.
_OWNER_MAP = {
    "SEO and development": "Mixed",
    "Development": "Developer",
    "SEO and content": "Mixed",
    "Content": "Content",
    "SEO and offsite outreach": "SEO",
    "SEO and analytics": "Mixed",
    "Analytics": "Analytics",
    "SEO": "SEO",
}


@dataclass
class WriteResult:
    """Recommendations plus metadata about how they were produced."""

    records: list[dict]
    ai_used: int
    fallback_used: int
    provider_name: str


def _fallback_record(row: dict) -> dict:
    """Map the rule-based recommendation onto the AI output schema."""
    base = build_recommendation(row)
    owner = _OWNER_MAP.get(base["implementation_owner"], "Mixed")
    rec = AiRecommendation(
        url=base["url"],
        bucket=base["bucket"],
        priority_score=base["priority_score"],
        primary_issue=base["primary_issue"],
        evidence=base["evidence"],
        recommended_actions=[base["recommended_action"]],
        risk_level=_RISK_BY_BUCKET.get(base["bucket"], "Low"),
        implementation_owner=owner,
        confidence=base["confidence"],
    )
    return rec.model_dump()


def _parse_json(raw: str) -> dict:
    """Parse a JSON object, tolerating accidental code fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        # Drop a leading language tag like "json".
        if "\n" in text:
            text = text.split("\n", 1)[1]
    return json.loads(text)


def _ai_record(row: dict, provider: Provider) -> dict:
    """Try the provider for one row; raise on any failure so caller falls back."""
    facts = build_facts(row)
    raw = provider.complete(SYSTEM_PROMPT, build_user_prompt(facts))
    data = _parse_json(raw)
    rec = AiRecommendation(**data)

    # Enforce authoritative values: the AI never sets scores or the bucket.
    rec.url = facts["url"]
    rec.bucket = facts["bucket"]
    rec.priority_score = facts["priority_score"]
    return rec.model_dump()


def write_recommendations(
    scored: pd.DataFrame,
    provider: Provider | None = None,
    top_n: int = 20,
) -> WriteResult:
    """Write recommendations for the top URLs, using AI when available.

    Args:
        scored: The scored master DataFrame (already sorted by priority).
        provider: An optional provider. If None or unavailable, every record is
            rule-based.
        top_n: How many top URLs to write recommendations for.

    Returns:
        A WriteResult with schema-valid records and counts of how many used AI
        versus the rule-based fallback.
    """
    limit = max(0, min(top_n, MAX_AI_URLS))
    selected = scored.head(limit)

    use_ai = provider is not None and provider.is_available()
    provider_name = provider.name if (provider is not None and use_ai) else "rule-based"

    records: list[dict] = []
    ai_used = 0
    fallback_used = 0

    for row in selected.to_dict(orient="records"):
        if use_ai:
            try:
                records.append(_ai_record(row, provider))
                ai_used += 1
                continue
            except Exception:
                # Any failure for this row falls back; never logs the payload.
                pass
        records.append(_fallback_record(row))
        fallback_used += 1

    return WriteResult(
        records=records,
        ai_used=ai_used,
        fallback_used=fallback_used,
        provider_name=provider_name,
    )
