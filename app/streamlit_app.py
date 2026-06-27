"""Streamlit MVP interface for Page Priority Intelligence.

Run locally with:
    streamlit run app/streamlit_app.py

Privacy posture: uploaded files are read into memory, processed, and offered
back as a download. Nothing is written to disk by this app. When the session
ends, the data is gone. There is no logging of URLs or metric values.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Make the src-layout package importable when run via `streamlit run`.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ppi.config import Settings  # noqa: E402
from ppi.ingestion.backlinks import load_backlinks  # noqa: E402
from ppi.ingestion.ga4 import load_ga4  # noqa: E402
from ppi.ingestion.gsc import load_gsc  # noqa: E402
from ppi.ingestion.pagespeed import load_pagespeed  # noqa: E402
from ppi.ingestion.screaming_frog import load_screaming_frog  # noqa: E402
from ppi.ingestion.url_inspection import load_url_inspection  # noqa: E402
from ppi.pipeline import run_pipeline  # noqa: E402
from ppi.ai.providers import get_provider  # noqa: E402
from ppi.ai.writer import write_recommendations  # noqa: E402
from ppi.reporting.report import (  # noqa: E402
    build_html_report,
    build_markdown_report,
)

DISCLAIMER = (
    "This tool prioritizes SEO work based on available data. It does not "
    "guarantee rankings, traffic, conversions, or indexing."
)


def _read(uploaded, loader, *args, warnings=None):
    """Read an uploaded file with the given loader, or return None if absent.

    Any data quality warnings (missing required or expected columns) are
    appended to the warnings list if one is provided.
    """
    if uploaded is None:
        return None
    return loader(uploaded.getvalue(), *args, warnings=warnings)


def main() -> None:
    st.set_page_config(page_title="Page Priority Intelligence", layout="wide")
    st.title("Page Priority Intelligence")
    st.caption("Local-first SEO page prioritization. CSV-upload MVP.")

    st.info(
        "Privacy: files are processed in memory and never stored on disk. "
        "No URLs or metrics are logged. " + DISCLAIMER
    )

    site_domain = st.text_input(
        "Site domain (required for GA4 landing-page matching)",
        value="https://example.com",
        help="Absolute origin with no trailing slash, e.g. https://example.com",
    ).strip()

    st.subheader("Upload exports")
    col1, col2 = st.columns(2)
    with col1:
        sf_file = st.file_uploader("Screaming Frog: Internal All (CSV)", type="csv")
        gsc_file = st.file_uploader("Google Search Console: Pages (CSV)", type="csv")
        ga4_file = st.file_uploader("GA4: Landing Pages (CSV)", type="csv")
    with col2:
        backlinks_file = st.file_uploader("Backlinks: Ahrefs/Semrush (CSV, optional)", type="csv")
        pagespeed_file = st.file_uploader("PageSpeed Insights (CSV, optional)", type="csv")
        inspection_file = st.file_uploader("URL Inspection (CSV, optional)", type="csv")

    st.subheader("AI recommendations (optional)")
    use_ai = st.checkbox(
        "Use AI to write recommendations",
        value=False,
        help=(
            "Off by default. When on, only structured facts for the top URLs "
            "(score, bucket, present metrics, evidence flags, and which metrics "
            "are missing) are sent. Raw uploads are never sent. The AI does not "
            "calculate scores. If no API key is configured, the tool falls back "
            "to rule-based recommendations."
        ),
    )
    ai_provider_name = ""
    if use_ai:
        ai_provider_name = st.selectbox(
            "Provider",
            options=["openai", "claude"],
            format_func=lambda v: {"openai": "OpenAI", "claude": "Claude (Anthropic)"}[v],
        )
        st.caption(
            "Set OPENAI_API_KEY or ANTHROPIC_API_KEY in your environment. Without "
            "a key the tool falls back to rule-based recommendations automatically."
        )

    if st.button("Score URLs", type="primary"):
        if sf_file is None or gsc_file is None:
            st.error(
                "Both a Screaming Frog crawl and a Search Console export are "
                "required for this MVP. GA4, backlinks, PageSpeed, and URL "
                "Inspection are optional."
            )
            return

        settings = Settings(site_domain=site_domain)
        ingestion_warnings: list[str] = []

        try:
            result = run_pipeline(
                settings,
                screaming_frog=_read(sf_file, load_screaming_frog, warnings=ingestion_warnings),
                gsc=_read(gsc_file, load_gsc, warnings=ingestion_warnings),
                ga4=_read(ga4_file, load_ga4, site_domain, warnings=ingestion_warnings),
                backlinks=_read(backlinks_file, load_backlinks, warnings=ingestion_warnings),
                pagespeed=_read(pagespeed_file, load_pagespeed, warnings=ingestion_warnings),
                url_inspection=_read(inspection_file, load_url_inspection, warnings=ingestion_warnings),
            )
        except Exception as exc:  # surface errors to the user, do not log data
            st.error(f"Could not score the uploaded files: {exc}")
            return

        scored = result.scored

        st.subheader("Results")
        c1, c2, c3 = st.columns(3)
        c1.metric("URLs scored", len(scored))
        c2.metric("Fix Now", int((scored["recommendation_bucket"] == "Fix Now").sum()))
        c3.metric("Quick Win", int((scored["recommendation_bucket"] == "Quick Win").sum()))

        all_warnings = ingestion_warnings + result.warnings
        if all_warnings:
            with st.expander("Data quality warnings", expanded=True):
                for warning in all_warnings:
                    st.warning(warning)

        st.markdown("**Bucket summary**")
        st.dataframe(
            scored["recommendation_bucket"].value_counts().rename_axis("bucket").reset_index(name="count"),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("**Top priority URLs**")
        st.dataframe(scored.head(20), use_container_width=True, hide_index=True)

        csv_bytes = scored.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download master scored CSV",
            data=csv_bytes,
            file_name="page_priority_scores.csv",
            mime="text/csv",
        )

        # Record which sources actually contributed, for the report.
        sources_used = [
            name
            for name, present in (
                ("Screaming Frog", sf_file is not None),
                ("Search Console", gsc_file is not None),
                ("GA4", ga4_file is not None),
                ("Backlinks", backlinks_file is not None),
                ("PageSpeed", pagespeed_file is not None),
                ("URL Inspection", inspection_file is not None),
            )
            if present
        ]

        markdown_report = build_markdown_report(scored, all_warnings, sources_used)
        st.download_button(
            "Download Markdown report",
            data=markdown_report.encode("utf-8"),
            file_name="page_priority_report.md",
            mime="text/markdown",
        )

        html_report = build_html_report(scored, all_warnings, sources_used)
        st.download_button(
            "Download HTML report",
            data=html_report.encode("utf-8"),
            file_name="page_priority_report.html",
            mime="text/html",
        )

        if use_ai:
            provider = get_provider(ai_provider_name)
            with st.spinner("Writing recommendations..."):
                ai_result = write_recommendations(scored, provider=provider, top_n=20)
            if ai_result.ai_used:
                st.success(
                    f"AI ({ai_result.provider_name}) wrote {ai_result.ai_used} "
                    f"recommendations; {ai_result.fallback_used} used the rule-based "
                    "fallback."
                )
            else:
                st.info(
                    "No usable AI provider was available, so all recommendations "
                    "use the rule-based writer. Set an API key to enable AI."
                )
            ai_json = json.dumps(ai_result.records, ensure_ascii=False, indent=2)
            st.download_button(
                "Download AI recommendations (JSON)",
                data=ai_json.encode("utf-8"),
                file_name="ai_recommendations.json",
                mime="application/json",
            )

        if not result.unmatched.empty:
            unmatched_bytes = result.unmatched.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download unmatched rows report",
                data=unmatched_bytes,
                file_name="unmatched_rows.csv",
                mime="text/csv",
            )


if __name__ == "__main__":
    main()
