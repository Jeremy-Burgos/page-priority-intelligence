"""Tests for URL normalization and GA4 path conversion."""

from __future__ import annotations

from ppi.normalization.url_tools import (
    NormalizeOptions,
    ga4_path_to_url,
    normalize_url,
    normalize_url_record,
    path_only,
)


def test_lowercases_scheme_and_host():
    assert normalize_url("HTTPS://Example.COM/Path/") == "https://example.com/Path/"


def test_strips_fragment():
    assert normalize_url("https://example.com/page/#section") == "https://example.com/page/"


def test_removes_tracking_params_but_keeps_real_ones():
    result = normalize_url("https://example.com/p/?utm_source=x&id=5&gclid=abc")
    assert result == "https://example.com/p/?id=5"


def test_sorts_remaining_query_params():
    a = normalize_url("https://example.com/p/?b=2&a=1")
    b = normalize_url("https://example.com/p/?a=1&b=2")
    assert a == b


def test_directory_path_gets_single_trailing_slash():
    assert normalize_url("https://example.com/services") == "https://example.com/services/"
    assert normalize_url("https://example.com/services///") == "https://example.com/services/"


def test_file_like_path_keeps_no_trailing_slash():
    assert normalize_url("https://example.com/sitemap.xml") == "https://example.com/sitemap.xml"


def test_root_path_preserved():
    assert normalize_url("https://example.com") == "https://example.com/"


def test_empty_input_returns_empty():
    assert normalize_url("") == ""
    assert normalize_url(None) == ""


def test_two_urls_differing_only_by_campaign_tags_match():
    a = normalize_url("https://example.com/page/?utm_campaign=spring")
    b = normalize_url("https://example.com/page/?fbclid=123")
    assert a == b == "https://example.com/page/"


def test_path_only_extraction():
    assert path_only("https://example.com/a/b/?x=1") == "/a/b/"


def test_ga4_path_to_full_url():
    result = ga4_path_to_url("/services/", "https://example.com")
    assert result == "https://example.com/services/"


def test_ga4_absolute_url_is_normalized():
    result = ga4_path_to_url("https://Example.com/Services", "https://example.com")
    assert result == "https://example.com/Services/"


def test_ga4_without_domain_returns_empty():
    assert ga4_path_to_url("/services/", "") == ""


# --- Configurable scheme forcing (requirement 1, test 1) ---

def test_http_to_https_when_configured():
    opts = NormalizeOptions(force_https=True)
    assert normalize_url("http://example.com/page/", opts) == "https://example.com/page/"


def test_http_left_untouched_by_default():
    # Default behavior must not silently rewrite the scheme.
    assert normalize_url("http://example.com/page/") == "http://example.com/page/"


def test_https_unchanged_when_force_https_on():
    opts = NormalizeOptions(force_https=True)
    assert normalize_url("https://example.com/page/", opts) == "https://example.com/page/"


# --- Query string preservation toggle (test 6) ---

def test_query_string_preserved_when_configured():
    opts = NormalizeOptions(keep_query=True)
    result = normalize_url("https://example.com/p/?id=5&page=2", opts)
    assert result == "https://example.com/p/?id=5&page=2"


def test_query_string_dropped_when_not_preserved():
    opts = NormalizeOptions(keep_query=False)
    result = normalize_url("https://example.com/p/?id=5&page=2", opts)
    assert result == "https://example.com/p/"


def test_tracking_params_removed_regardless_of_query_setting():
    opts = NormalizeOptions(keep_query=True)
    result = normalize_url("https://example.com/p/?utm_source=x&id=5", opts)
    assert result == "https://example.com/p/?id=5"


# --- Source URL preservation and match confidence (requirements 6 and 8) ---

def test_record_preserves_source_url():
    record = normalize_url_record("https://Example.com/Page/?utm_source=x#top")
    assert record["source_url"] == "https://Example.com/Page/?utm_source=x#top"
    assert record["normalized_url"] == "https://example.com/Page/"


def test_record_absolute_url_is_high_confidence():
    record = normalize_url_record("https://example.com/page/")
    assert record["match_confidence"] == "high"
    assert record["match_method"] == "absolute"


def test_record_reconstructed_path_is_medium_confidence():
    record = normalize_url_record("/services/", site_domain="https://example.com")
    assert record["normalized_url"] == "https://example.com/services/"
    assert record["match_confidence"] == "medium"
    assert record["match_method"] == "path_reconstructed"


def test_record_path_without_domain_is_low_confidence():
    record = normalize_url_record("/services/", site_domain="")
    assert record["normalized_url"] == ""
    assert record["match_confidence"] == "low"
    assert record["match_method"] == "path_no_domain"


def test_record_empty_input_is_low_confidence():
    record = normalize_url_record("")
    assert record["normalized_url"] == ""
    assert record["match_confidence"] == "low"
    assert record["match_method"] == "empty"


def test_record_schemeless_host_is_low_confidence():
    # "example.com/page" has no scheme, so it cannot be trusted as a join key.
    record = normalize_url_record("example.com/page")
    assert record["match_confidence"] == "low"
    assert record["match_method"] == "unparseable"


def test_record_honors_force_https_option():
    opts = NormalizeOptions(force_https=True)
    record = normalize_url_record("http://example.com/page/", options=opts)
    assert record["normalized_url"] == "https://example.com/page/"
    assert record["match_confidence"] == "high"
