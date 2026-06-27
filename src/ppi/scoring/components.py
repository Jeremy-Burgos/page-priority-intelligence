"""Component score functions.

Each function returns a float in 0.0 to 1.0 for one row. They are deliberately
pure (no DataFrame state beyond the passed baselines and optional context) so
they can be unit-tested in isolation. The priority module combines them.

Where the project spec was directional rather than exact, the heuristic chosen
here is documented in docs/scoring_model.md under "Stated assumptions" so the
math stays inspectable rather than hidden.
"""

from __future__ import annotations

from typing import Optional

from ppi.scoring.baselines import Baselines, expected_ctr, ranking_opportunity
from ppi.scoring.normalize_metrics import normalize_log


def _num(value: object) -> Optional[float]:
    """Return value as float, or None if it is missing, NaN, or non-numeric."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    # NaN compares unequal to itself; a missing joined cell is not a value.
    if numeric != numeric:
        return None
    return numeric


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# Demand
# --------------------------------------------------------------------------- #
def demand_score(row: dict, baselines: Baselines) -> float:
    """How much search demand this page already attracts or sits near.

    Demand = 0.60 normalized impressions + 0.20 normalized query count
             + 0.20 ranking opportunity.
    """
    norm_impr = normalize_log(row.get("gsc_impressions"), baselines.p90_impressions)
    norm_queries = normalize_log(row.get("gsc_query_count"), baselines.p90_query_count)
    rank_opp = ranking_opportunity(row.get("gsc_avg_position"))
    return _clamp(0.60 * norm_impr + 0.20 * norm_queries + 0.20 * rank_opp)


# --------------------------------------------------------------------------- #
# Underperformance
# --------------------------------------------------------------------------- #
def ctr_gap_score(row: dict, baselines: Baselines) -> float:
    """CTR shortfall against the expected CTR for the page's ranking band.

    Returns the fractional gap, 0.0 to 1.0, where 0.0 means CTR is at or above
    the band median and 1.0 means CTR is effectively zero against a positive
    expectation. Returns 0.0 when CTR or position is missing. Isolated as its
    own function so the Quick Win bucket can key off the CTR gap specifically
    rather than the blended underperformance score.
    """
    actual_ctr = _num(row.get("gsc_ctr"))
    position = row.get("gsc_avg_position")
    if actual_ctr is None or _num(position) is None:
        return 0.0
    exp = expected_ctr(baselines, position)
    if exp <= 0:
        return 0.0
    return _clamp((exp - actual_ctr) / exp)


def underperformance_score(row: dict, baselines: Baselines) -> float:
    """How far below its potential the page is performing.

    Underperformance = 0.40 CTR gap + 0.25 click gap + 0.20 GA4 session gap
                       + 0.15 engagement/conversion gap.
    """
    norm_impr = normalize_log(row.get("gsc_impressions"), baselines.p90_impressions)
    norm_clicks = normalize_log(row.get("gsc_clicks"), baselines.p90_clicks)
    norm_sessions = normalize_log(row.get("ga4_sessions"), baselines.p90_sessions)

    ctr_gap = ctr_gap_score(row, baselines)

    # Click gap: impressions clearly outrunning clicks signals lost potential.
    click_gap = _clamp(norm_impr - norm_clicks)

    # GA4 session gap: search clicks not translating into landing sessions.
    session_gap = _clamp(norm_clicks - norm_sessions) if norm_sessions > 0 else 0.0

    # Engagement gap: low engagement rate where GA4 data exists.
    engagement_rate = _num(row.get("ga4_engagement_rate"))
    engagement_gap = _clamp(1.0 - engagement_rate) if engagement_rate is not None else 0.0

    return _clamp(
        0.40 * ctr_gap + 0.25 * click_gap + 0.20 * session_gap + 0.15 * engagement_gap
    )


# --------------------------------------------------------------------------- #
# Technical risk
# --------------------------------------------------------------------------- #
def technical_risk_score(row: dict, duplicate_titles: Optional[set] = None) -> float:
    """Severity of technical issues blocking or limiting the page.

    Technical Risk = 0.25 indexability + 0.20 status code + 0.15 canonical
                     + 0.15 robots/noindex + 0.10 metadata + 0.10 content
                     + 0.05 crawl depth.
    """
    duplicate_titles = duplicate_titles or set()

    # Indexability problem.
    indexability = str(row.get("indexability") or "").lower()
    indexability_problem = 1.0 if indexability.startswith("non") else 0.0

    # Status code problem (only when a code is present and not 200).
    status_code = _num(row.get("status_code"))
    status_problem = 1.0 if (status_code is not None and int(status_code) != 200) else 0.0

    # Canonical problem: Google-selected canonical differs from user-declared.
    canonical_match = row.get("canonical_match")
    canonical_problem = 0.80 if canonical_match is False else 0.0

    # Robots/noindex problem.
    status_text = str(row.get("indexability_status") or "").lower()
    robots_state = str(row.get("url_inspection_robots_state") or "").lower()
    has_impressions = (_num(row.get("gsc_impressions")) or 0) > 0
    noindex = "noindex" in status_text
    blocked = "robots" in status_text or "disallow" in robots_state or "blocked" in robots_state
    # Noindex on a page that still earns impressions is the worst case.
    robots_problem = 1.0 if ((noindex and has_impressions) or blocked) else (0.6 if noindex else 0.0)

    # Metadata problem: take the most severe single metadata issue. A field
    # that is absent (None, e.g. a page with no crawl data) is unknown and is
    # not penalized; only a field that was crawled and is genuinely empty counts.
    def _crawled_empty(value: object) -> bool:
        return value is not None and str(value).strip() == ""

    title_raw = row.get("title")
    title = str(title_raw or "").strip()
    meta_issues = [0.0]
    if _crawled_empty(title_raw):
        meta_issues.append(0.60)
    elif title and title in duplicate_titles:
        meta_issues.append(0.40)
    if _crawled_empty(row.get("meta_description")):
        meta_issues.append(0.30)
    if _crawled_empty(row.get("h1")):
        meta_issues.append(0.30)
    metadata_problem = max(meta_issues)

    # Content thinness problem.
    word_count = _num(row.get("word_count"))
    content_problem = 0.30 if (word_count is not None and word_count < 200) else 0.0

    # Crawl depth problem.
    crawl_depth = _num(row.get("crawl_depth"))
    depth_problem = 0.30 if (crawl_depth is not None and crawl_depth > 4) else 0.0

    return _clamp(
        0.25 * indexability_problem
        + 0.20 * status_problem
        + 0.15 * canonical_problem
        + 0.15 * robots_problem
        + 0.10 * metadata_problem
        + 0.10 * content_problem
        + 0.05 * depth_problem
    )


# --------------------------------------------------------------------------- #
# Authority / internal link gap
# --------------------------------------------------------------------------- #
def referring_domain_gap(row: dict, baselines: Baselines) -> float:
    """External authority shortfall from referring domains (0 to 1).

    1.0 means no external authority relative to the site; 0.0 means at or above
    the site's P90 referring domains. Kept separate from the internal link gap
    so the bucket layer can distinguish an Authority Gap from an Internal Link
    Push, which the combined score alone cannot do.
    """
    norm_ref_domains = normalize_log(
        row.get("referring_domains"), baselines.p90_referring_domains
    )
    return _clamp(1.0 - norm_ref_domains)


def internal_link_gap(row: dict, baselines: Baselines) -> float:
    """Internal linking shortfall from inlinks (0 to 1).

    1.0 means almost no internal links relative to the site; 0.0 means at or
    above the site's P90 inlinks.
    """
    norm_inlinks = normalize_log(row.get("inlinks"), baselines.p90_inlinks)
    return _clamp(1.0 - norm_inlinks)


def authority_internal_link_gap(row: dict, baselines: Baselines) -> float:
    """Structural authority and internal linking shortfall.

    Gap = 0.50 referring domain gap + 0.30 internal link gap
          + 0.20 crawl depth gap. Referring domains are weighted above raw
    backlinks because they are the more reliable authority signal.
    """
    referring_gap = referring_domain_gap(row, baselines)
    internal_gap = internal_link_gap(row, baselines)

    crawl_depth = _num(row.get("crawl_depth"))
    if crawl_depth is None:
        crawl_depth_gap = 0.0
    else:
        # Depth 1 is no gap; depth 6 or deeper is a full gap.
        crawl_depth_gap = _clamp((crawl_depth - 1) / 5.0)

    return _clamp(
        0.50 * referring_gap + 0.30 * internal_gap + 0.20 * crawl_depth_gap
    )


# --------------------------------------------------------------------------- #
# Performance risk and traffic value
# --------------------------------------------------------------------------- #
def performance_risk_score(row: dict) -> float:
    """Core Web Vitals and Lighthouse risk.

    Performance Risk = 0.35 LCP + 0.35 INP + 0.20 CLS + 0.10 Lighthouse.
    Thresholds follow Google's good/poor boundaries.
    """
    lcp = _num(row.get("psi_lcp"))
    inp = _num(row.get("psi_inp"))
    cls = _num(row.get("psi_cls"))
    perf_score = _num(row.get("psi_performance_score"))

    # LCP seconds: 2.5 good, 4.0 poor.
    lcp_risk = _clamp((lcp - 2.5) / (4.0 - 2.5)) if lcp is not None else 0.0
    # INP milliseconds: 200 good, 500 poor.
    inp_risk = _clamp((inp - 200) / (500 - 200)) if inp is not None else 0.0
    # CLS ratio: 0.1 good, 0.25 poor.
    cls_risk = _clamp((cls - 0.1) / (0.25 - 0.1)) if cls is not None else 0.0
    # Lighthouse performance score on a 0 to 100 scale.
    lighthouse_risk = _clamp(1.0 - (perf_score / 100.0)) if perf_score is not None else 0.0

    return _clamp(
        0.35 * lcp_risk + 0.35 * inp_risk + 0.20 * cls_risk + 0.10 * lighthouse_risk
    )


def traffic_value_score(row: dict, baselines: Baselines) -> float:
    """How much real traffic value a page carries.

    Used so performance fixes are prioritized on pages that actually matter.
    MVP heuristic: 0.40 sessions + 0.30 clicks + 0.20 conversions + 0.10 revenue,
    all log-normalized. Documented as an assumption in scoring_model.md.
    """
    norm_sessions = normalize_log(row.get("ga4_sessions"), baselines.p90_sessions)
    norm_clicks = normalize_log(row.get("gsc_clicks"), baselines.p90_clicks)
    norm_conversions = normalize_log(row.get("ga4_conversions"), baselines.p90_conversions)
    norm_revenue = normalize_log(row.get("ga4_revenue"), baselines.p90_revenue)
    return _clamp(
        0.40 * norm_sessions
        + 0.30 * norm_clicks
        + 0.20 * norm_conversions
        + 0.10 * norm_revenue
    )


# --------------------------------------------------------------------------- #
# Decay
# --------------------------------------------------------------------------- #
def decay_score(row: dict) -> float:
    """Decline risk from current vs previous period fields.

    Decay = 0.40 click decline + 0.30 impression decline + 0.20 session decline
            + 0.10 conversion decline. Each decline is the fractional drop from
    the previous period, floored at 0. Returns 0.0 when no period data exists,
    which is the case for the CSV MVP unless current/previous columns are added.
    """

    def decline(current_key: str, previous_key: str) -> float:
        current = _num(row.get(current_key))
        previous = _num(row.get(previous_key))
        if current is None or previous is None or previous <= 0:
            return 0.0
        return _clamp((previous - current) / previous)

    return _clamp(
        0.40 * decline("gsc_current_clicks", "gsc_previous_clicks")
        + 0.30 * decline("gsc_current_impressions", "gsc_previous_impressions")
        + 0.20 * decline("ga4_current_sessions", "ga4_previous_sessions")
        + 0.10 * decline("ga4_current_conversions", "ga4_previous_conversions")
    )


# --------------------------------------------------------------------------- #
# Business value
# --------------------------------------------------------------------------- #
def business_value_score(row: dict, baselines: Baselines) -> float:
    """Direct commercial value of the page.

    Business Value = 0.50 normalized conversions + 0.30 normalized revenue
                     + 0.20 manual strategic importance (0 to 1).
    """
    norm_conversions = normalize_log(row.get("ga4_conversions"), baselines.p90_conversions)
    norm_revenue = normalize_log(row.get("ga4_revenue"), baselines.p90_revenue)
    manual = _num(row.get("business_importance"))
    manual = _clamp(manual) if manual is not None else 0.0
    return _clamp(0.50 * norm_conversions + 0.30 * norm_revenue + 0.20 * manual)
