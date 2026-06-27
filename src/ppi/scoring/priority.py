"""Priority score combination and confidence.

This module turns the component scores into the final 0 to 100 priority score
using the project weights, and assigns a confidence level based on how many
sources actually contributed to the row.
"""

from __future__ import annotations

from typing import Optional

from ppi.config import PriorityWeights
from ppi.scoring import components
from ppi.scoring.baselines import Baselines


def score_row(
    row: dict,
    baselines: Baselines,
    weights: PriorityWeights,
    duplicate_titles: Optional[set] = None,
) -> dict:
    """Compute every component and the final priority score for one row.

    Args:
        row: A joined per-URL record (a dict).
        baselines: Sitewide baselines.
        weights: Top-level priority weights.
        duplicate_titles: Set of titles that appear more than once sitewide,
            used by the metadata portion of technical risk.

    Returns:
        A dict of all component scores plus priority_score. The caller merges
        these onto the row.
    """
    demand = components.demand_score(row, baselines)
    underperformance = components.underperformance_score(row, baselines)
    ctr_gap = components.ctr_gap_score(row, baselines)
    technical = components.technical_risk_score(row, duplicate_titles)
    authority = components.authority_internal_link_gap(row, baselines)
    referring_gap = components.referring_domain_gap(row, baselines)
    internal_gap = components.internal_link_gap(row, baselines)
    performance = components.performance_risk_score(row)
    traffic_value = components.traffic_value_score(row, baselines)
    decay = components.decay_score(row)
    business = components.business_value_score(row, baselines)

    # Opportunity products: risk and underperformance only matter where there
    # is demand or traffic value to justify the work.
    seo_opportunity = demand * underperformance
    technical_opportunity = demand * technical
    performance_opportunity = traffic_value * performance

    priority = 100.0 * (
        weights.seo_opportunity * seo_opportunity
        + weights.technical_risk_opportunity * technical_opportunity
        + weights.authority_internal_link_gap * authority
        + weights.performance_risk_opportunity * performance_opportunity
        + weights.decay_risk * decay
        + weights.business_value * business
    )

    return {
        "demand_score": round(demand, 4),
        "underperformance_score": round(underperformance, 4),
        "ctr_gap_score": round(ctr_gap, 4),
        "seo_opportunity_score": round(seo_opportunity, 4),
        "technical_risk_score": round(technical, 4),
        "technical_risk_opportunity_score": round(technical_opportunity, 4),
        "authority_internal_link_gap_score": round(authority, 4),
        "referring_domain_gap": round(referring_gap, 4),
        "internal_link_gap": round(internal_gap, 4),
        "performance_risk_score": round(performance, 4),
        "performance_risk_opportunity_score": round(performance_opportunity, 4),
        "traffic_value_score": round(traffic_value, 4),
        "decay_score": round(decay, 4),
        "business_value_score": round(business, 4),
        "priority_score": round(min(priority, 100.0), 2),
    }


def confidence_for_row(row: dict, sources_present: dict[str, bool]) -> str:
    """Assign High, Medium, or Low confidence for a row.

    Confidence rises with the number of independent sources backing the row.

    Args:
        row: The joined record (used to check whether key metrics are present).
        sources_present: Flags for which source files were uploaded at all,
            keyed by "screaming_frog", "gsc", "ga4", "pagespeed",
            "url_inspection", "backlinks".

    Returns:
        "High", "Medium", or "Low".
    """
    sf = sources_present.get("screaming_frog", False)
    gsc = sources_present.get("gsc", False)
    ga4 = sources_present.get("ga4", False)
    extras = any(
        sources_present.get(k, False)
        for k in ("pagespeed", "url_inspection", "backlinks")
    )

    # Whether this specific row actually carries GSC and GA4 values, not just
    # whether the files were uploaded. A joined-but-empty cell is NaN, which
    # must not count as present.
    def _present(value: object) -> bool:
        if value is None:
            return False
        try:
            return float(value) == float(value)  # False only for NaN
        except (TypeError, ValueError):
            return bool(str(value).strip())

    row_has_gsc = _present(row.get("gsc_impressions")) or _present(row.get("gsc_clicks"))
    row_has_ga4 = _present(row.get("ga4_sessions")) or _present(row.get("ga4_conversions"))

    if sf and gsc and ga4 and extras and row_has_gsc and row_has_ga4:
        return "High"
    if sf and gsc and row_has_gsc:
        return "Medium"
    return "Low"
