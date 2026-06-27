"""Tests for CSV ingestion: column mapping and data quality warnings.

These verify requirements 2, 3, 6, and 7: variant column headers map to internal
fields, missing required columns are flagged, missing expected columns produce
warnings without failing, and the loaders remain callable without a warnings
accumulator (backward compatibility).
"""

from __future__ import annotations

from ppi.ingestion.backlinks import load_backlinks
from ppi.ingestion.ga4 import load_ga4
from ppi.ingestion.gsc import load_gsc
from ppi.ingestion.pagespeed import load_pagespeed
from ppi.ingestion.screaming_frog import load_screaming_frog
from ppi.ingestion.url_inspection import load_url_inspection


def _b(text: str) -> bytes:
    return text.encode("utf-8")


# --- Column mapping (requirement 2) ---

def test_gsc_maps_variant_position_header():
    # "Average Position" should resolve to gsc_avg_position.
    csv = _b("Page,Clicks,Impressions,CTR,Average Position\n"
             "https://example.com/a/,10,1000,0.01,8.0\n")
    df = load_gsc(csv)
    assert len(df) == 1
    assert df.iloc[0]["gsc_avg_position"] == 8.0


def test_screaming_frog_maps_address_to_url():
    csv = _b("Address,Status Code,Indexability\n"
             "https://example.com/a/,200,Indexable\n")
    df = load_screaming_frog(csv)
    assert len(df) == 1
    assert df.iloc[0]["url"] == "https://example.com/a/"
    assert df.iloc[0]["normalized_url"] == "https://example.com/a/"


# --- Missing expected columns warn but do not fail (requirement 6) ---

def test_gsc_missing_expected_columns_warns():
    csv = _b("Page,Clicks,Impressions\nhttps://example.com/a/,10,1000\n")
    warnings: list[str] = []
    df = load_gsc(csv, warnings=warnings)
    assert len(df) == 1  # still returns data
    joined = " ".join(warnings)
    assert "gsc_ctr" in joined
    assert "gsc_avg_position" in joined
    assert all("expected column" in w for w in warnings)


def test_pagespeed_missing_metric_columns_warns():
    csv = _b("URL,Performance score\nhttps://example.com/a/,90\n")
    warnings: list[str] = []
    load_pagespeed(csv, warnings=warnings)
    joined = " ".join(warnings)
    assert "psi_lcp" in joined
    assert "psi_inp" in joined
    assert "psi_cls" in joined


# --- Missing required column produces a severe warning (requirement 3) ---

def test_gsc_missing_url_column_warns_required():
    csv = _b("Clicks,Impressions,CTR,Position\n10,1000,0.01,8.0\n")
    warnings: list[str] = []
    df = load_gsc(csv, warnings=warnings)
    assert len(df) == 0  # no URL means nothing joinable
    assert any("required column" in w and "url" in w for w in warnings)


def test_screaming_frog_missing_required_status_warns():
    csv = _b("Address,Indexability\nhttps://example.com/a/,Indexable\n")
    warnings: list[str] = []
    df = load_screaming_frog(csv, warnings=warnings)
    assert len(df) == 1  # URL present, so the row survives
    assert any("required column" in w and "status_code" in w for w in warnings)


# --- No warnings list still works (backward compatibility) ---

def test_loaders_callable_without_warnings_arg():
    csv = _b("Page,Clicks,Impressions,CTR,Position\n"
             "https://example.com/a/,10,1000,0.01,8.0\n")
    df = load_gsc(csv)
    assert len(df) == 1


# --- GA4 required field is the landing page, not url ---

def test_ga4_missing_landing_page_warns_required():
    csv = _b("Sessions,Conversions\n100,5\n")
    warnings: list[str] = []
    df = load_ga4(csv, "https://example.com", warnings=warnings)
    assert len(df) == 0
    assert any("required column" in w and "landing_page" in w for w in warnings)


def test_ga4_path_is_converted_with_domain():
    csv = _b("Landing page,Sessions,Conversions\n/services/,100,5\n")
    warnings: list[str] = []
    df = load_ga4(csv, "https://example.com", warnings=warnings)
    assert len(df) == 1
    assert df.iloc[0]["normalized_url"] == "https://example.com/services/"


# --- Optional sources warn but never raise (requirement 7 at column level) ---

def test_backlinks_missing_expected_warns_not_raises():
    csv = _b("URL\nhttps://example.com/a/\n")
    warnings: list[str] = []
    df = load_backlinks(csv, warnings=warnings)
    assert len(df) == 1
    joined = " ".join(warnings)
    assert "referring_domains" in joined


def test_url_inspection_missing_canonical_columns_warns():
    csv = _b("Inspection URL,Coverage state\nhttps://example.com/a/,Indexed\n")
    warnings: list[str] = []
    df = load_url_inspection(csv, warnings=warnings)
    assert len(df) == 1
    joined = " ".join(warnings)
    assert "google_canonical" in joined or "user_canonical" in joined


# --- CTR percentage parsing (sub-1% regression) ---

def test_gsc_ctr_sub_one_percent_parsed_correctly():
    # "0.40%" must become 0.004, not 0.40. This is the common case for
    # underperforming pages and previously inflated CTR by 100x.
    csv = _b("Page,Clicks,Impressions,CTR,Position\n"
             "https://example.com/a/,40,10000,0.40%,8.0\n")
    df = load_gsc(csv)
    assert abs(df.iloc[0]["gsc_ctr"] - 0.004) < 1e-9


def test_gsc_ctr_whole_percent_parsed_correctly():
    csv = _b("Page,Clicks,Impressions,CTR,Position\n"
             "https://example.com/a/,40,1000,3.4%,5.0\n")
    df = load_gsc(csv)
    assert abs(df.iloc[0]["gsc_ctr"] - 0.034) < 1e-9


def test_gsc_ctr_api_fraction_unchanged():
    # An API-style decimal fraction with no percent sign is kept as-is.
    csv = _b("Page,Clicks,Impressions,CTR,Position\n"
             "https://example.com/a/,40,1000,0.034,5.0\n")
    df = load_gsc(csv)
    assert abs(df.iloc[0]["gsc_ctr"] - 0.034) < 1e-9
