"""Validated schema for AI recommendation output.

The AI must return JSON matching exactly this shape. Anything that does not
validate is rejected and the caller falls back to the rule-based writer, so a
malformed or hallucinated response can never reach the report.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AiRecommendation(BaseModel):
    """One per-URL recommendation, matching the required output schema."""

    url: str
    bucket: str
    priority_score: float = 0.0
    primary_issue: str = ""
    evidence: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    risk_level: str = ""
    implementation_owner: str = ""
    confidence: str = ""

    @field_validator("evidence", "recommended_actions", mode="before")
    @classmethod
    def _coerce_list(cls, value: object) -> list:
        """Accept a single string where a list is expected, coerce to a list."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            return [str(v) for v in value if str(v).strip()]
        return [str(value)]

    @field_validator("confidence")
    @classmethod
    def _require_confidence(cls, value: str) -> str:
        """Confidence must be present; empty is not allowed (requirement 7)."""
        if not str(value).strip():
            raise ValueError("confidence is required")
        return value
