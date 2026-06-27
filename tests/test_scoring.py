"""Tests for scoring components, the priority combiner, and the pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from ppi.config import PriorityWeights, Settings
from ppi.ingestion.backlinks import load_backlinks
from ppi.ingestion.ga4 import load_ga4
from ppi.ingestion.gsc import load_gsc
from ppi.ingestion.pagespeed import load_pagespeed
from ppi.ingestion.screaming_frog import load_screaming_frog
from ppi.ingestion.url_inspection import load_url_inspection
from ppi.pipeline import run_pipeline
from ppi.scoring import components
from ppi.scoring.baselines import Baselines, ranking_band, ranking_opportunity
from ppi.scoring.buckets import assign_bucket
from ppi.scoring.normalize_metrics import normalize_log, p90
from ppi.scoring.priority import score_row

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


# --------------------------------------------------------------------------- #
# Normalization primitive
# --------------------------------------------------------------------------- #
def test_normalize_log_caps_at_one():
    assert normalize_log(10_000, 100) == 1.0


def test_normalize_log_zero_and_missing():
    assert normalize_log(0, 100) == 0.0
    assert normalize_log(None, 100) == 0.0
    assert normalize_log(50, 0) == 0.0


def test_normalize_log_monotonic():
    low = normalize_log(10, 1000)
    high = normalize_log(500, 1000)
    assert 0.0 < low < high < 1.0


def test_p90_handles_empty():
    import pandas as pd

    assert p90(pd.Series(dtype="float64")) == 0.0


# --------------------------------------------------------------------------- #
# Ranking bands
# --------------------------------------------------------------------------- #
def test_ranking_band_boundaries():
    assert ranking_band(2) == "1-3"
    assert ranking_band(7) == "4-10"
    assert ranking_band(15) == "11-20"
    assert ranking_band(40) == "21-50"
    assert ranking_band(80) == "51+"
    assert ranking_band(None) == "no_data"


def test_ranking_opportunity_peaks_at_4_to_10():
    assert ranking_opportunity(7) == 1.00
    assert ranking_opportunity(2) == 0.30
    assert ranking_opportunity(None) == 0.00


# --------------------------------------------------------------------------- #
# Components
# --------------------------------------------------------------------------- #
def _baselines() -> Baselines:
    return Baselines(
        p90_impressions=50000,
        p90_query_count=400,
        p90_clicks=2000,
        p90_sessions=3000,
        p90_conversions=180,
        p90_revenue=20000,
        p90_referring_domains=400,
        p90_inlinks=140,
        median_inlinks=20,
        ctr_median_by_band={"4-10": 0.03},
        global_ctr_median=0.02,
    )


def test_technical_risk_flags_non_200():
    row = {"status_code": 404, "indexability": "Non-Indexable"}
    assert components.technical_risk_score(row) > 0.4


def test_technical_risk_clean_page_is_low():
    row = {
        "status_code": 200,
        "indexability": "Indexable",
        "title": "A good title",
        "meta_description": "A description.",
        "h1": "An H1",
        "word_count": 1200,
        "crawl_depth": 1,
    }
    assert components.technical_risk_score(row) == 0.0


def test_noindex_with_impressions_is_severe():
    row = {
        "indexability": "Non-Indexable",
        "indexability_status": "Noindex",
        "gsc_impressions": 1200,
    }
    assert components.technical_risk_score(row) >= 0.4


def test_underperformance_ctr_gap():
    # Page in 4-10 band with CTR well below the band median of 0.03.
    row = {
        "gsc_impressions": 15000,
        "gsc_clicks": 50,
        "gsc_ctr": 0.004,
        "gsc_avg_position": 6.8,
        "ga4_sessions": 200,
    }
    assert components.underperformance_score(row, _baselines()) > 0.0


def test_business_value_uses_conversions():
    high = components.business_value_score(
        {"ga4_conversions": 180, "ga4_revenue": 20000}, _baselines()
    )
    low = components.business_value_score(
        {"ga4_conversions": 0, "ga4_revenue": 0}, _baselines()
    )
    assert high > low


def test_performance_risk_thresholds():
    good = components.performance_risk_score(
        {"psi_lcp": 2.0, "psi_inp": 150, "psi_cls": 0.05, "psi_performance_score": 90}
    )
    bad = components.performance_risk_score(
        {"psi_lcp": 5.0, "psi_inp": 600, "psi_cls": 0.4, "psi_performance_score": 30}
    )
    # Good vitals leave only the small residual from a sub-100 Lighthouse score.
    assert good < 0.05
    assert bad > 0.8


# --------------------------------------------------------------------------- #
# Priority combination
# --------------------------------------------------------------------------- #
def test_priority_score_in_range():
    weights = PriorityWeights()
    row = {
        "gsc_impressions": 15000,
        "gsc_clicks": 40,
        "gsc_ctr": 0.004,
        "gsc_avg_position": 6.8,
        "ga4_sessions": 260,
        "ga4_conversions": 22,
        "ga4_revenue": 8200,
        "referring_domains": 4,
        "inlinks": 18,
        "status_code": 200,
        "indexability": "Indexable",
        "title": "Our Services",
        "word_count": 310,
    }
    result = score_row(row, _baselines(), weights)
    assert 0.0 <= result["priority_score"] <= 100.0
    assert 0.0 <= result["demand_score"] <= 1.0


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        PriorityWeights(seo_opportunity=0.9).validate()


# --------------------------------------------------------------------------- #
# End-to-end pipeline on the sample data
# --------------------------------------------------------------------------- #
def test_pipeline_end_to_end():
    settings = Settings(site_domain="https://example.com")

    sf = load_screaming_frog(SAMPLE_DIR / "screaming_frog_internal_all_template.csv")
    gsc = load_gsc(SAMPLE_DIR / "gsc_pages_template.csv")
    ga4 = load_ga4(SAMPLE_DIR / "ga4_landing_pages_template.csv", settings.site_domain)
    backlinks = load_backlinks(SAMPLE_DIR / "backlinks_template.csv")
    pagespeed = load_pagespeed(SAMPLE_DIR / "pagespeed_template.csv")
    url_inspection = load_url_inspection(SAMPLE_DIR / "url_inspection_template.csv")

    result = run_pipeline(
        settings,
        screaming_frog=sf,
        gsc=gsc,
        ga4=ga4,
        backlinks=backlinks,
        pagespeed=pagespeed,
        url_inspection=url_inspection,
    )

    scored = result.scored

    # Every crawled URL is scored exactly once.
    assert len(scored) == len(sf)
    assert scored["priority_score"].between(0, 100).all()

    # Sorted descending by priority.
    assert scored["priority_score"].is_monotonic_decreasing

    # The 404 page must be flagged Fix Now (it has impressions and a bad status).
    broken = scored[scored["url"] == "https://example.com/broken-page/"]
    assert not broken.empty
    assert broken.iloc[0]["recommendation_bucket"] == "Fix Now"

    # Every row carries a bucket and a confidence label.
    assert scored["recommendation_bucket"].notna().all()
    assert scored["confidence_score"].isin(["High", "Medium", "Low"]).all()


def test_pipeline_requires_a_base_source():
    settings = Settings(site_domain="https://example.com")
    with pytest.raises(ValueError):
        run_pipeline(settings)


# --------------------------------------------------------------------------- #
# Score ranges: every component must return 0.0 to 1.0
# --------------------------------------------------------------------------- #
_RANGE_ROWS = [
    {},  # entirely missing
    {  # rich row
        "gsc_impressions": 90000, "gsc_clicks": 50, "gsc_ctr": 0.001,
        "gsc_avg_position": 6.5, "gsc_query_count": 600, "ga4_sessions": 5,
        "ga4_conversions": 0, "ga4_revenue": 0, "ga4_engagement_rate": 0.1,
        "referring_domains": 0, "inlinks": 0, "crawl_depth": 9,
        "status_code": 404, "indexability": "Non-Indexable",
        "indexability_status": "Noindex", "word_count": 20,
        "psi_lcp": 6.0, "psi_inp": 700, "psi_cls": 0.5, "psi_performance_score": 10,
    },
    {  # strong healthy row
        "gsc_impressions": 100, "gsc_clicks": 90, "gsc_ctr": 0.9,
        "gsc_avg_position": 1.2, "ga4_sessions": 9000, "ga4_conversions": 500,
        "ga4_revenue": 99999, "referring_domains": 9000, "inlinks": 9000,
        "crawl_depth": 1, "status_code": 200, "indexability": "Indexable",
        "title": "T", "meta_description": "M", "h1": "H", "word_count": 3000,
        "psi_lcp": 1.0, "psi_inp": 50, "psi_cls": 0.0, "psi_performance_score": 100,
    },
]


def test_every_component_stays_in_unit_range():
    b = _baselines()
    for row in _RANGE_ROWS:
        for value in (
            components.demand_score(row, b),
            components.underperformance_score(row, b),
            components.technical_risk_score(row),
            components.authority_internal_link_gap(row, b),
            components.referring_domain_gap(row, b),
            components.internal_link_gap(row, b),
            components.performance_risk_score(row),
            components.traffic_value_score(row, b),
            components.decay_score(row),
            components.business_value_score(row, b),
        ):
            assert 0.0 <= value <= 1.0


def test_priority_score_never_exceeds_100_on_extreme_row():
    # Maximize every driver at once; the cap must still hold.
    b = _baselines()
    row = _RANGE_ROWS[1]
    result = score_row(row, b, PriorityWeights())
    assert 0.0 <= result["priority_score"] <= 100.0


# --------------------------------------------------------------------------- #
# Missing data handling
# --------------------------------------------------------------------------- #
def test_score_row_on_empty_row_does_not_crash():
    result = score_row({}, _baselines(), PriorityWeights())
    assert 0.0 <= result["priority_score"] <= 100.0
    for key, value in result.items():
        if key.endswith("_score") and key != "priority_score":
            assert 0.0 <= value <= 1.0


def test_score_row_treats_nan_as_missing():
    # A left join leaves NaN in unmatched cells. NaN must not corrupt the math
    # or produce a NaN priority (the bug fixed earlier in development). Demand
    # collapses to 0 with no GSC data. The priority is not exactly 0 because the
    # Authority/Internal Link Gap is a standalone term in the specified formula
    # (not demand-gated), and a page with no measured links has a maximal gap.
    nan = float("nan")
    row = {
        "gsc_impressions": nan, "gsc_clicks": nan, "gsc_ctr": nan,
        "gsc_avg_position": nan, "ga4_sessions": nan, "ga4_conversions": nan,
        "referring_domains": nan, "inlinks": nan, "status_code": nan,
        "psi_lcp": nan, "psi_inp": nan, "psi_cls": nan,
    }
    result = score_row(row, _baselines(), PriorityWeights())
    assert result["priority_score"] == result["priority_score"]  # not NaN
    assert result["demand_score"] == 0.0
    assert result["seo_opportunity_score"] == 0.0
    assert 0.0 <= result["priority_score"] < 20.0


def test_partial_row_only_crawl_data_is_low_priority():
    # A crawled 200 page with no GSC/GA4 should score low, not high.
    row = {"status_code": 200, "indexability": "Indexable", "title": "T",
           "meta_description": "M", "h1": "H", "word_count": 800, "crawl_depth": 2}
    result = score_row(row, _baselines(), PriorityWeights())
    assert result["demand_score"] == 0.0
    assert result["priority_score"] < 20.0


def test_components_accept_missing_keys_individually():
    b = _baselines()
    assert components.demand_score({}, b) == 0.0
    assert components.technical_risk_score({}) == 0.0
    assert components.performance_risk_score({}) == 0.0
    assert components.decay_score({}) == 0.0
    assert components.business_value_score({}, b) == 0.0


# --------------------------------------------------------------------------- #
# Bucket assignment inputs: one test per bucket, aligned to the stated rules
# --------------------------------------------------------------------------- #
ALL_BUCKETS = {
    "Fix Now", "Performance Fix", "Quick Win", "Protect", "Refresh/Expand",
    "Authority Gap", "Internal Link Push", "Merge/Prune", "Monitor",
}


def test_bucket_fix_now():
    # Rule 1: demand or business value plus a serious technical blocker.
    row = {"demand_score": 0.5, "technical_risk_score": 0.6}
    assert assign_bucket(row)[0] == "Fix Now"


def test_bucket_fix_now_via_business_value():
    # Fix Now should also fire on a high-value page even without search demand.
    row = {"demand_score": 0.0, "business_value_score": 0.7, "technical_risk_score": 0.6}
    assert assign_bucket(row)[0] == "Fix Now"


def test_bucket_performance_fix_on_traffic():
    # Rule 6: poor Core Web Vitals on a page with traffic value.
    row = {"demand_score": 0.0, "technical_risk_score": 0.0,
           "performance_risk_score": 0.6, "traffic_value_score": 0.6}
    assert assign_bucket(row)[0] == "Performance Fix"


def test_bucket_performance_fix_on_demand_only():
    # Rule 6 explicitly includes demand, not only traffic. A high-demand page
    # with poor CWV but no session data yet must still be a Performance Fix.
    row = {"demand_score": 0.5, "technical_risk_score": 0.0,
           "performance_risk_score": 0.6, "traffic_value_score": 0.0,
           "business_value_score": 0.0}
    assert assign_bucket(row)[0] == "Performance Fix"


def test_bucket_quick_win_keys_off_ctr_gap():
    # Rule 2: high impressions, position 4 to 20, CTR below expected.
    row = {"demand_score": 0.5, "technical_risk_score": 0.0,
           "performance_risk_score": 0.0, "traffic_value_score": 0.0,
           "business_value_score": 0.0, "ctr_gap_score": 0.5,
           "gsc_avg_position": 6.0}
    assert assign_bucket(row)[0] == "Quick Win"


def test_quick_win_not_triggered_without_ctr_gap():
    # A striking-distance page with NO CTR gap is not a Quick Win, even if the
    # blended underperformance score is high from other gaps.
    row = {"demand_score": 0.5, "technical_risk_score": 0.0,
           "performance_risk_score": 0.0, "traffic_value_score": 0.0,
           "business_value_score": 0.0, "ctr_gap_score": 0.0,
           "underperformance_score": 0.6, "gsc_avg_position": 6.0,
           "word_count": 1500}
    assert assign_bucket(row)[0] != "Quick Win"


def test_bucket_refresh_expand_on_thin_content():
    # Rule 3: demand with weak content signals.
    row = {"demand_score": 0.5, "technical_risk_score": 0.0,
           "performance_risk_score": 0.0, "ctr_gap_score": 0.0,
           "business_value_score": 0.2, "gsc_avg_position": 40.0,
           "word_count": 120}
    assert assign_bucket(row)[0] == "Refresh/Expand"


def test_bucket_refresh_expand_on_low_engagement():
    # Rule 3: demand with weak engagement.
    row = {"demand_score": 0.5, "technical_risk_score": 0.0,
           "performance_risk_score": 0.0, "ctr_gap_score": 0.0,
           "business_value_score": 0.2, "gsc_avg_position": 40.0,
           "word_count": 1500, "ga4_engagement_rate": 0.2}
    assert assign_bucket(row)[0] == "Refresh/Expand"


def test_bucket_protect():
    # Rule 7: performs well, low risk, not declining.
    row = {"demand_score": 0.5, "technical_risk_score": 0.1,
           "performance_risk_score": 0.0, "ctr_gap_score": 0.0,
           "underperformance_score": 0.2, "decay_score": 0.0,
           "business_value_score": 0.7, "word_count": 1500}
    assert assign_bucket(row)[0] == "Protect"


def test_bucket_authority_gap():
    # Rule 5: demand but weak referring domains.
    row = {"demand_score": 0.5, "technical_risk_score": 0.0,
           "performance_risk_score": 0.0, "ctr_gap_score": 0.0,
           "underperformance_score": 0.2, "business_value_score": 0.2,
           "decay_score": 0.0, "referring_domain_gap": 0.7,
           "internal_link_gap": 0.2, "gsc_avg_position": 40.0,
           "word_count": 1500}
    assert assign_bucket(row)[0] == "Authority Gap"


def test_bucket_internal_link_push_on_weak_inlinks():
    # Rule 4: demand with weak internal links, referring gap low so Authority
    # Gap does not intercept first.
    row = {"demand_score": 0.5, "technical_risk_score": 0.0,
           "performance_risk_score": 0.0, "ctr_gap_score": 0.0,
           "underperformance_score": 0.2, "business_value_score": 0.2,
           "decay_score": 0.0, "referring_domain_gap": 0.2,
           "internal_link_gap": 0.7, "gsc_avg_position": 40.0,
           "word_count": 1500}
    assert assign_bucket(row)[0] == "Internal Link Push"


def test_bucket_internal_link_push_on_deep_crawl():
    # Rule 4 also fires on high crawl depth even when inlink gap is moderate.
    row = {"demand_score": 0.5, "technical_risk_score": 0.0,
           "performance_risk_score": 0.0, "ctr_gap_score": 0.0,
           "underperformance_score": 0.2, "business_value_score": 0.2,
           "decay_score": 0.0, "referring_domain_gap": 0.2,
           "internal_link_gap": 0.3, "gsc_avg_position": 40.0,
           "word_count": 1500, "crawl_depth": 7}
    assert assign_bucket(row)[0] == "Internal Link Push"


def test_bucket_merge_prune():
    # Rule 8: low impressions, clicks, sessions, links, and weak content.
    row = {"demand_score": 0.03, "traffic_value_score": 0.02,
           "business_value_score": 0.0, "technical_risk_score": 0.0,
           "performance_risk_score": 0.0, "referring_domain_gap": 1.0,
           "word_count": 80}
    assert assign_bucket(row)[0] == "Merge/Prune"


def test_merge_prune_not_triggered_for_substantial_content():
    # A long page with no traffic is not auto-pruned; it falls through to Monitor.
    row = {"demand_score": 0.03, "traffic_value_score": 0.02,
           "business_value_score": 0.0, "technical_risk_score": 0.0,
           "performance_risk_score": 0.0, "referring_domain_gap": 1.0,
           "word_count": 2000}
    assert assign_bucket(row)[0] != "Merge/Prune"


def test_bucket_monitor_default():
    # Rule 9: insufficient signal for any action.
    row = {"demand_score": 0.15, "traffic_value_score": 0.15,
           "business_value_score": 0.15, "technical_risk_score": 0.0,
           "performance_risk_score": 0.0, "referring_domain_gap": 0.3,
           "internal_link_gap": 0.3, "word_count": 1500}
    assert assign_bucket(row)[0] == "Monitor"


def test_bucket_always_returns_a_known_label():
    for row in _RANGE_ROWS:
        scored = score_row(row, _baselines(), PriorityWeights())
        bucket, recommendation = assign_bucket(scored)
        assert bucket in ALL_BUCKETS
        assert isinstance(recommendation, str) and recommendation
