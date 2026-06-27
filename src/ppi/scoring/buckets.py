"""Recommendation bucket assignment.

Each URL is assigned exactly one primary bucket using a priority-ordered set of
rules. The rules below implement the project's nine bucket definitions. Order
matters because a page can satisfy more than one rule; the order encodes triage
logic so the single assigned bucket is the most important action for that page.

Evaluation order and the reasoning for it:
  1. Fix Now          - a technical block prevents every other gain, so unblock first.
  2. Performance Fix   - poor Core Web Vitals cap gains on a page that has value.
  3. Quick Win         - highest ROI: close a CTR gap on a striking-distance page.
  4. Refresh/Expand    - demand with weak content or engagement.
  5. Protect           - a well-performing, valuable page that should not be churned.
  6. Authority Gap     - demand held back by thin external authority.
  7. Internal Link Push - demand held back by weak internal links or deep crawl depth.
  8. Merge/Prune       - genuinely low-signal page across the board.
  9. Monitor           - insufficient data or no clear action.

Performance Fix is placed above Quick Win deliberately: a slow page in striking
distance should have its Core Web Vitals fixed before its title is rewritten,
because the speed problem suppresses any CTR gain. This is a defensible triage
order rather than the literal listing order; the thresholds and order are
explicit constants so they can be tuned.

All thresholds are explicit so the reasoning behind each bucket is auditable.
"""

from __future__ import annotations

from ppi.scoring.baselines import ranking_band
from ppi.scoring.components import _num

# Score thresholds (0 to 1 unless noted).
DEMAND_MEANINGFUL = 0.25
TECH_RISK_BLOCKING = 0.40
PERF_RISK_HIGH = 0.40
TRAFFIC_VALUE_MEANINGFUL = 0.40
CONVERSION_VALUE_MEANINGFUL = 0.40
CTR_GAP_QUICK_WIN = 0.30
UNDERPERF_HIGH = 0.40
AUTHORITY_GAP_HIGH = 0.60
INTERNAL_LINK_GAP_HIGH = 0.60
BUSINESS_VALUE_HIGH = 0.50
DECAY_HIGH = 0.30
LOW_SIGNAL = 0.10
LOW_ENGAGEMENT_RATE = 0.50  # GA4 engagement rate below this is weak
THIN_CONTENT_WORDS = 300    # word count below this is weak content
DEEP_CRAWL_DEPTH = 4        # crawl depth greater than this is too deep


def _is_thin_content(row: dict) -> bool:
    """True only when word count was crawled and is below the thin threshold.

    An absent word count is unknown, not weak, so it does not count as thin.
    """
    word_count = _num(row.get("word_count"))
    return word_count is not None and word_count < THIN_CONTENT_WORDS


def _is_low_engagement(row: dict) -> bool:
    """True only when a GA4 engagement rate is present and below the threshold."""
    rate = _num(row.get("ga4_engagement_rate"))
    return rate is not None and rate < LOW_ENGAGEMENT_RATE


def _is_deep(row: dict) -> bool:
    """True only when crawl depth is present and deeper than the threshold."""
    depth = _num(row.get("crawl_depth"))
    return depth is not None and depth > DEEP_CRAWL_DEPTH


def assign_bucket(row: dict) -> tuple[str, str]:
    """Return (bucket, primary_recommendation) for a scored row.

    Args:
        row: A row that already contains all component scores plus context
            fields such as gsc_impressions, gsc_avg_position, word_count,
            ga4_engagement_rate, and crawl_depth.

    Returns:
        A tuple of the bucket name and a short evidence-based recommendation.
    """
    demand = row.get("demand_score", 0.0)
    technical = row.get("technical_risk_score", 0.0)
    underperformance = row.get("underperformance_score", 0.0)
    ctr_gap = row.get("ctr_gap_score", 0.0)
    performance = row.get("performance_risk_score", 0.0)
    traffic_value = row.get("traffic_value_score", 0.0)
    business = row.get("business_value_score", 0.0)
    decay = row.get("decay_score", 0.0)

    # Combined gap with sub-gaps. Fall back to the combined score for callers
    # that do not provide the separated sub-gaps.
    authority = row.get("authority_internal_link_gap_score", 0.0)
    referring_gap = row.get("referring_domain_gap", authority)
    internal_gap = row.get("internal_link_gap", authority)

    band = ranking_band(row.get("gsc_avg_position"))
    has_demand = demand >= DEMAND_MEANINGFUL
    has_value = traffic_value >= TRAFFIC_VALUE_MEANINGFUL or business >= CONVERSION_VALUE_MEANINGFUL

    # 1. Fix Now: serious technical blocker on a page with demand or value.
    if technical >= TECH_RISK_BLOCKING and (has_demand or business >= BUSINESS_VALUE_HIGH):
        return (
            "Fix Now",
            "Resolve the technical blocker (indexability, status code, robots, "
            "or canonical) before any content or link work.",
        )

    # 2. Performance Fix: poor Core Web Vitals on a page with traffic,
    #    conversions, or demand.
    if performance >= PERF_RISK_HIGH and (has_value or has_demand):
        return (
            "Performance Fix",
            "Improve Core Web Vitals (LCP, INP, or CLS) on a page that carries "
            "traffic, conversions, or search demand.",
        )

    # 3. Quick Win: high impressions, position 4 to 20, CTR below expected.
    if has_demand and band in {"4-10", "11-20"} and ctr_gap >= CTR_GAP_QUICK_WIN:
        return (
            "Quick Win",
            "Rewrite the title and meta description to close the CTR gap on a "
            "page ranking in striking distance with existing impressions.",
        )

    # 4. Refresh/Expand: demand with weak content signals or weak engagement.
    if has_demand and (_is_thin_content(row) or _is_low_engagement(row) or underperformance >= UNDERPERF_HIGH):
        return (
            "Refresh/Expand",
            "Refresh and expand the content and improve engagement for a page "
            "that has demand but weak content or engagement signals.",
        )

    # 5. Protect: well-performing, valuable page that should not be churned.
    if (
        business >= BUSINESS_VALUE_HIGH
        and technical < TECH_RISK_BLOCKING
        and performance < PERF_RISK_HIGH
        and underperformance < UNDERPERF_HIGH
        and decay < DECAY_HIGH
    ):
        return (
            "Protect",
            "Monitor and defend this page; it already performs and converts, so "
            "avoid aggressive changes.",
        )

    # 6. Authority Gap: demand but weak referring domains or external authority.
    if has_demand and referring_gap >= AUTHORITY_GAP_HIGH:
        return (
            "Authority Gap",
            "Build referring domains; the page has demand but weak external "
            "authority relative to the site.",
        )

    # 7. Internal Link Push: demand with weak internal links or deep crawl depth.
    if has_demand and (internal_gap >= INTERNAL_LINK_GAP_HIGH or _is_deep(row)):
        return (
            "Internal Link Push",
            "Add internal links from relevant pages and reduce crawl depth for a "
            "page that has demand but weak internal linking.",
        )

    # 8. Merge/Prune: low across impressions, clicks, sessions, links, and content.
    if (
        demand < LOW_SIGNAL
        and traffic_value < LOW_SIGNAL
        and business < LOW_SIGNAL
        and referring_gap >= (1.0 - LOW_SIGNAL)
        and not _content_is_substantial(row)
    ):
        return (
            "Merge/Prune",
            "Consider merging into a stronger page or pruning; low impressions, "
            "clicks, sessions, links, and weak content.",
        )

    # 9. Monitor: default when no rule fires or data is insufficient.
    return (
        "Monitor",
        "No strong signal yet or insufficient data; keep under review as more "
        "data becomes available.",
    )


def _content_is_substantial(row: dict) -> bool:
    """True when word count is present and at or above the thin threshold.

    Used by Merge/Prune so a long page is not pruned. Absent word count does
    not block pruning, since a dead page may simply lack crawl content data.
    """
    word_count = _num(row.get("word_count"))
    return word_count is not None and word_count >= THIN_CONTENT_WORDS
