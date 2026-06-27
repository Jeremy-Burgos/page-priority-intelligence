"""Central configuration for Page Priority Intelligence.

All tunable values live here so scoring stays transparent and adjustable
without editing logic. Nothing in this file is a secret. Real credentials,
if API integrations are added later, belong in a local .env file that is
never committed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Tracking parameters stripped during URL normalization so that the same page
# requested with different campaign tags joins to a single row.
TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "msclkid",
        "ref",
        "_ga",
    }
)


@dataclass(frozen=True)
class PriorityWeights:
    """Top-level weights for the final priority score.

    These must sum to 1.0. They are kept here so the formula in code always
    matches the formula in docs/scoring_model.md.
    """

    seo_opportunity: float = 0.35
    technical_risk_opportunity: float = 0.20
    authority_internal_link_gap: float = 0.15
    performance_risk_opportunity: float = 0.10
    decay_risk: float = 0.10
    business_value: float = 0.10

    def validate(self) -> None:
        """Raise if the weights do not sum to 1.0 within a small tolerance."""
        total = (
            self.seo_opportunity
            + self.technical_risk_opportunity
            + self.authority_internal_link_gap
            + self.performance_risk_opportunity
            + self.decay_risk
            + self.business_value
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"Priority weights must sum to 1.0, got {total}")


@dataclass(frozen=True)
class Settings:
    """Runtime settings for a single analysis session.

    site_domain is required to turn GA4 landing-page paths (which are usually
    stored as "/path/" rather than full URLs) into absolute URLs that can join
    against the crawl and Search Console data.
    """

    site_domain: str = ""  # e.g. "https://example.com" (no trailing slash)
    weights: PriorityWeights = field(default_factory=PriorityWeights)
    percentile_for_normalization: float = 0.90  # P90 baseline per the model

    def __post_init__(self) -> None:
        self.weights.validate()


# A module-level default that callers can override per session.
DEFAULT_SETTINGS = Settings()
