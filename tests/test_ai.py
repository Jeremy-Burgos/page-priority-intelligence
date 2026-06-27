"""Tests for the optional AI recommendation writer.

No network is used. Providers are faked so the AI path and the fallback path are
both exercised deterministically.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from ppi.ai.facts import build_facts
from ppi.ai.providers import ClaudeProvider, OpenAIProvider, get_provider
from ppi.ai.schema import AiRecommendation
from ppi.ai.writer import MAX_AI_URLS, write_recommendations


def _row(**over) -> dict:
    base = {
        "url": "https://example.com/services/seo-audit/",
        "recommendation_bucket": "Quick Win",
        "priority_score": 25.84,
        "primary_recommendation": "Rewrite the title and meta description.",
        "confidence_score": "Medium",
        "gsc_impressions": 15000,
        "gsc_avg_position": 6.8,
        "gsc_ctr": 0.004,
        "ctr_gap_score": 0.6,
        "status_code": 200,
        "indexability": "Indexable",
    }
    base.update(over)
    return base


def _df(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows) or [_row()])


class FakeProvider:
    name = "fake"

    def __init__(self, payload: dict | str, available: bool = True):
        self._payload = payload
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if isinstance(self._payload, str):
            return self._payload
        return json.dumps(self._payload)


# --------------------------------------------------------------------------- #
# Structured facts boundary
# --------------------------------------------------------------------------- #
def test_build_facts_only_contains_allowed_keys():
    facts = build_facts(_row())
    assert set(facts.keys()) == {
        "url", "bucket", "priority_score", "metrics",
        "evidence_flags", "missing_data", "confidence",
    }
    # Metrics are per-URL aggregates, never a raw dataset payload.
    assert isinstance(facts["metrics"], dict)
    assert "gsc_impressions" in facts["metrics"]


def test_build_facts_lists_missing_metrics():
    facts = build_facts(_row(ga4_sessions=None, referring_domains=None))
    assert "ga4_sessions" in facts["missing_data"]
    assert "referring_domains" in facts["missing_data"]
    assert "ga4_sessions" not in facts["metrics"]


# --------------------------------------------------------------------------- #
# Fallback behavior
# --------------------------------------------------------------------------- #
def test_fallback_when_no_provider():
    result = write_recommendations(_df(), provider=None, top_n=5)
    assert result.fallback_used == 1
    assert result.ai_used == 0
    assert result.provider_name == "rule-based"
    rec = result.records[0]
    assert rec["risk_level"]      # requirement: risk level present
    assert rec["confidence"]      # requirement 7: confidence present
    assert isinstance(rec["recommended_actions"], list)


def test_fallback_when_provider_unavailable():
    provider = FakeProvider({}, available=False)
    result = write_recommendations(_df(), provider=provider, top_n=5)
    assert result.ai_used == 0
    assert result.fallback_used == 1


def test_fallback_records_are_schema_valid():
    result = write_recommendations(_df(), provider=None, top_n=5)
    # Re-validation through the schema must not raise.
    AiRecommendation(**result.records[0])


# --------------------------------------------------------------------------- #
# AI path
# --------------------------------------------------------------------------- #
def _valid_ai_payload(url: str) -> dict:
    return {
        "url": url,
        "bucket": "Quick Win",
        "priority_score": 25.84,
        "primary_issue": "CTR is below the band expectation.",
        "evidence": ["Impressions are high.", "Position is 6.8."],
        "recommended_actions": ["Rewrite the title.", "Improve the meta description."],
        "risk_level": "Medium",
        "implementation_owner": "Mixed",
        "confidence": "Medium",
    }


def test_ai_path_used_when_provider_available():
    provider = FakeProvider(_valid_ai_payload("https://example.com/services/seo-audit/"))
    result = write_recommendations(_df(), provider=provider, top_n=5)
    assert result.ai_used == 1
    assert result.fallback_used == 0
    assert result.provider_name == "fake"
    assert "Rewrite the title." in result.records[0]["recommended_actions"]


def test_ai_cannot_change_scores_or_bucket():
    # Provider tries to inflate the score and change the bucket and URL.
    tampered = _valid_ai_payload("https://evil.example/other/")
    tampered["priority_score"] = 99.9
    tampered["bucket"] = "Protect"
    provider = FakeProvider(tampered)
    result = write_recommendations(_df(), provider=provider, top_n=5)
    rec = result.records[0]
    # Authoritative values are restored from the scored row.
    assert rec["priority_score"] == 25.84
    assert rec["bucket"] == "Quick Win"
    assert rec["url"] == "https://example.com/services/seo-audit/"


def test_invalid_json_falls_back():
    provider = FakeProvider("this is not json", available=True)
    result = write_recommendations(_df(), provider=provider, top_n=5)
    assert result.ai_used == 0
    assert result.fallback_used == 1


def test_missing_confidence_falls_back():
    payload = _valid_ai_payload("https://example.com/services/seo-audit/")
    payload["confidence"] = ""  # schema rejects empty confidence
    provider = FakeProvider(payload)
    result = write_recommendations(_df(), provider=provider, top_n=5)
    assert result.fallback_used == 1


def test_code_fenced_json_is_parsed():
    payload = _valid_ai_payload("https://example.com/services/seo-audit/")
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    provider = FakeProvider(fenced)
    result = write_recommendations(_df(), provider=provider, top_n=5)
    assert result.ai_used == 1


# --------------------------------------------------------------------------- #
# Limits and provider selection
# --------------------------------------------------------------------------- #
def test_ai_url_cap_is_enforced():
    rows = [_row(url=f"https://example.com/p{i}/") for i in range(MAX_AI_URLS + 10)]
    provider = FakeProvider(_valid_ai_payload("x"))
    result = write_recommendations(_df(*rows), provider=provider, top_n=1000)
    assert len(result.records) == MAX_AI_URLS


def test_get_provider_names():
    assert isinstance(get_provider("openai"), OpenAIProvider)
    assert isinstance(get_provider("claude"), ClaudeProvider)
    assert get_provider("") is None
    assert get_provider("unknown") is None


def test_schema_coerces_string_action_to_list():
    rec = AiRecommendation(
        url="u", bucket="Monitor", confidence="Low",
        recommended_actions="A single action",
    )
    assert rec.recommended_actions == ["A single action"]
