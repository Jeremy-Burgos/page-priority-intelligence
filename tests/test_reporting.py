"""Tests for Markdown and HTML report generation.

These build reports from the real scored output of the sample pipeline and from
small synthetic frames, and verify section presence, HTML escaping, and that
both reports cover every bucket without crashing on empty inputs.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ppi.config import Settings
from ppi.ingestion.gsc import load_gsc
from ppi.ingestion.screaming_frog import load_screaming_frog
from ppi.pipeline import run_pipeline
from ppi.reporting.recommendations import build_recommendation
from ppi.reporting.report import (
    BUCKET_ORDER,
    build_html_report,
    build_markdown_report,
)

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data"


def _scored():
    settings = Settings(site_domain="https://example.com")
    return run_pipeline(
        settings,
        screaming_frog=load_screaming_frog(SAMPLE_DIR / "screaming_frog_internal_all_template.csv"),
        gsc=load_gsc(SAMPLE_DIR / "gsc_pages_template.csv"),
    ).scored


def test_markdown_report_has_required_sections():
    md = build_markdown_report(_scored(), warnings=[], sources_used=["Screaming Frog", "Search Console"])
    for section in [
        "# Page Priority Intelligence Report",
        "## Executive Summary",
        "## Data Sources Used",
        "## Data Quality Warnings",
        "## Methodology",
        "## Scoring Explanation",
        "## Next Steps",
    ]:
        assert section in md
    # Every bucket gets its own section (Merge/Prune uses "Candidates" wording).
    headings = {"Merge/Prune": "Merge/Prune Candidates"}
    for bucket in BUCKET_ORDER:
        expected = headings.get(bucket, f"{bucket} URLs")
        assert f"## {expected}" in md


def test_markdown_report_lists_sources_and_warnings():
    md = build_markdown_report(
        _scored(),
        warnings=["Search Console: expected column for 'gsc_ctr' was not found."],
        sources_used=["Screaming Frog", "Search Console"],
    )
    assert "Screaming Frog, Search Console" in md
    assert "gsc_ctr" in md


def test_markdown_report_handles_no_warnings():
    md = build_markdown_report(_scored(), warnings=[], sources_used=["Screaming Frog"])
    assert "No data quality warnings were raised." in md


def test_html_report_is_well_formed_and_has_sections():
    html_doc = build_html_report(_scored(), warnings=[], sources_used=["Screaming Frog", "Search Console"])
    assert html_doc.startswith("<!DOCTYPE html>")
    assert html_doc.rstrip().endswith("</html>")
    assert "Executive Summary" in html_doc
    assert "Methodology" in html_doc
    for bucket in BUCKET_ORDER:
        assert bucket in html_doc


def test_html_report_escapes_dynamic_content():
    # A URL containing markup must be escaped, not rendered.
    frame = pd.DataFrame(
        [
            {
                "url": "https://example.com/<script>alert(1)</script>",
                "priority_score": 50.0,
                "recommendation_bucket": "Quick Win",
                "confidence_score": "Low",
                "primary_recommendation": "Test & verify",
            }
        ]
    )
    html_doc = build_html_report(frame, warnings=[], sources_used=["Test"])
    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;" in html_doc
    assert "Test &amp; verify" in html_doc


def test_reports_handle_empty_frame():
    empty = pd.DataFrame(
        columns=["url", "priority_score", "recommendation_bucket",
                 "confidence_score", "primary_recommendation"]
    )
    md = build_markdown_report(empty, warnings=[], sources_used=[])
    html_doc = build_html_report(empty, warnings=[], sources_used=[])
    assert "Page Priority Intelligence Report" in md
    assert "No URLs in this bucket." in md
    assert "No URLs in this bucket." in html_doc


def test_markdown_table_escapes_pipe_characters():
    frame = pd.DataFrame(
        [
            {
                "url": "https://example.com/a/",
                "priority_score": 40.0,
                "recommendation_bucket": "Monitor",
                "confidence_score": "Low",
                "primary_recommendation": "Compare A | B options",
            }
        ]
    )
    md = build_markdown_report(frame, warnings=[], sources_used=[])
    # The literal pipe inside a cell must be escaped so the table stays valid.
    assert "A \\| B" in md


# --------------------------------------------------------------------------- #
# Per-URL recommendation: all eight fields
# --------------------------------------------------------------------------- #
def test_build_recommendation_has_eight_fields():
    row = {
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
    }
    rec = build_recommendation(row)
    for field in (
        "url", "bucket", "priority_score", "primary_issue", "evidence",
        "recommended_action", "implementation_owner", "confidence",
    ):
        assert field in rec
    assert isinstance(rec["evidence"], list) and rec["evidence"]
    assert rec["implementation_owner"]  # bucket-derived owner is set
    # Evidence must cite real values from the row.
    joined = " ".join(rec["evidence"])
    assert "15,000" in joined
    assert "6.8" in joined


def test_recommendation_owner_varies_by_bucket():
    fix = build_recommendation({"recommendation_bucket": "Fix Now"})
    perf = build_recommendation({"recommendation_bucket": "Performance Fix"})
    assert fix["implementation_owner"] != perf["implementation_owner"]


def test_markdown_bucket_sections_render_eight_fields():
    md = build_markdown_report(_scored(), warnings=[], sources_used=["Screaming Frog", "Search Console"])
    for label in (
        "Primary issue:", "Evidence:", "Recommended action:",
        "Implementation owner:", "Confidence:",
    ):
        assert label in md


def test_html_bucket_sections_render_eight_fields():
    html_doc = build_html_report(_scored(), warnings=[], sources_used=["Screaming Frog", "Search Console"])
    for label in (
        "Primary issue", "Evidence", "Recommended action",
        "Implementation owner", "Confidence",
    ):
        assert label in html_doc


def test_merge_prune_heading_uses_candidates_wording():
    md = build_markdown_report(_scored(), warnings=[], sources_used=[])
    assert "Merge/Prune Candidates" in md


def test_report_section_order_matches_spec():
    md = build_markdown_report(_scored(), warnings=[], sources_used=[])
    order = [
        "Fix Now URLs", "Quick Win URLs", "Refresh/Expand URLs",
        "Internal Link Push URLs", "Authority Gap URLs", "Performance Fix URLs",
        "Merge/Prune Candidates", "Protect URLs",
    ]
    positions = [md.index(f"## {name}") for name in order]
    assert positions == sorted(positions)


def test_evidence_skips_missing_values():
    # A row with almost nothing should not fabricate evidence.
    rec = build_recommendation({"recommendation_bucket": "Monitor", "url": "https://example.com/x/"})
    assert rec["evidence"]  # never empty
    joined = " ".join(rec["evidence"]).lower()
    assert "insufficient data" in joined
