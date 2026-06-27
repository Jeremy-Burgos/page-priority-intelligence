"""End-to-end scoring pipeline.

Takes already-ingested per-source DataFrames, joins them on normalized_url with
the crawl as the base universe, computes baselines once, scores every row,
assigns one bucket per row, and returns the master scored table plus an
unmatched-rows report. No file is read or written here; callers (the Streamlit
app, tests, or a future CLI) own input and output. This keeps the MVP's privacy
promise: nothing is persisted by the logic layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from ppi.config import Settings
from ppi.scoring.baselines import compute_baselines
from ppi.scoring.buckets import assign_bucket
from ppi.scoring.priority import confidence_for_row, score_row

# Column order for the master output, matching the report output spec.
MASTER_COLUMNS = [
    "url",
    "status_code",
    "indexability",
    "gsc_clicks",
    "gsc_impressions",
    "gsc_ctr",
    "gsc_avg_position",
    "ga4_sessions",
    "ga4_conversions",
    "referring_domains",
    "inlinks",
    "psi_lcp",
    "psi_inp",
    "psi_cls",
    "demand_score",
    "underperformance_score",
    "technical_risk_score",
    "authority_internal_link_gap_score",
    "performance_risk_score",
    "decay_score",
    "business_value_score",
    "priority_score",
    "recommendation_bucket",
    "primary_recommendation",
    "confidence_score",
]


@dataclass
class PipelineResult:
    """The output of a scoring run."""

    scored: pd.DataFrame  # full master table
    unmatched: pd.DataFrame  # rows from non-crawl sources that did not join
    warnings: list[str]  # data-quality notes for the report


def _merge_source(
    base: pd.DataFrame, source: Optional[pd.DataFrame], label: str, warnings: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Left-join a source onto the base universe by normalized_url.

    Returns the merged base and the unmatched rows from the source so nothing
    is dropped silently.
    """
    if source is None or source.empty:
        return base, pd.DataFrame()

    source = source[source["normalized_url"].astype(bool)].copy()
    matched_keys = set(base["normalized_url"])
    unmatched = source[~source["normalized_url"].isin(matched_keys)].copy()
    if not unmatched.empty:
        unmatched["unmatched_source"] = label
        warnings.append(
            f"{len(unmatched)} {label} row(s) did not match a crawled URL and were "
            f"excluded from scoring."
        )

    # Drop the source's own url column to avoid clobbering the base url.
    join_cols = [c for c in source.columns if c not in {"url", "landing_page"}]
    merged = base.merge(
        source[join_cols].drop_duplicates(subset="normalized_url"),
        on="normalized_url",
        how="left",
        suffixes=("", f"_{label}"),
    )
    return merged, unmatched


def run_pipeline(
    settings: Settings,
    screaming_frog: Optional[pd.DataFrame] = None,
    gsc: Optional[pd.DataFrame] = None,
    ga4: Optional[pd.DataFrame] = None,
    backlinks: Optional[pd.DataFrame] = None,
    pagespeed: Optional[pd.DataFrame] = None,
    url_inspection: Optional[pd.DataFrame] = None,
) -> PipelineResult:
    """Join all available sources and produce the master scored table.

    Screaming Frog defines the URL universe. If it is absent, the pipeline falls
    back to GSC as the base so the tool still runs, with a warning.

    Args:
        settings: Session settings, including weights and site domain.
        screaming_frog, gsc, ga4, backlinks, pagespeed, url_inspection:
            Ingested per-source DataFrames, or None if not provided.

    Returns:
        A PipelineResult with the scored table, unmatched rows, and warnings.
    """
    warnings: list[str] = []

    if screaming_frog is not None and not screaming_frog.empty:
        base = screaming_frog.copy()
    elif gsc is not None and not gsc.empty:
        base = gsc.copy()
        warnings.append(
            "Screaming Frog crawl was not provided; using Search Console URLs as "
            "the base universe. Technical risk scores will be limited."
        )
    else:
        raise ValueError(
            "At least a Screaming Frog or GSC export is required to build the URL universe."
        )

    base = base[base["normalized_url"].astype(bool)].drop_duplicates(subset="normalized_url")

    unmatched_frames: list[pd.DataFrame] = []
    for source, label in (
        (gsc, "gsc"),
        (ga4, "ga4"),
        (backlinks, "backlinks"),
        (pagespeed, "pagespeed"),
        (url_inspection, "url_inspection"),
    ):
        # Skip re-merging gsc if it is already the base.
        if label == "gsc" and base is gsc:
            continue
        base, unmatched = _merge_source(base, source, label, warnings)
        if not unmatched.empty:
            unmatched_frames.append(unmatched)

    sources_present = {
        "screaming_frog": screaming_frog is not None and not screaming_frog.empty,
        "gsc": gsc is not None and not gsc.empty,
        "ga4": ga4 is not None and not ga4.empty,
        "backlinks": backlinks is not None and not backlinks.empty,
        "pagespeed": pagespeed is not None and not pagespeed.empty,
        "url_inspection": url_inspection is not None and not url_inspection.empty,
    }

    baselines = compute_baselines(base)

    # Titles that appear more than once feed the duplicate-title metadata check.
    duplicate_titles: set = set()
    if "title" in base.columns:
        titles = base["title"].dropna()
        titles = titles[titles.astype(str).str.strip() != ""]
        counts = titles.value_counts()
        duplicate_titles = set(counts[counts > 1].index)

    scored_records: list[dict] = []
    for record in base.to_dict(orient="records"):
        scores = score_row(record, baselines, settings.weights, duplicate_titles)
        record.update(scores)
        bucket, recommendation = assign_bucket(record)
        record["recommendation_bucket"] = bucket
        record["primary_recommendation"] = recommendation
        record["confidence_score"] = confidence_for_row(record, sources_present)
        scored_records.append(record)

    scored = pd.DataFrame(scored_records)
    scored = scored.sort_values("priority_score", ascending=False).reset_index(drop=True)

    # Present the spec columns first; keep any extra context columns after them.
    present_master = [c for c in MASTER_COLUMNS if c in scored.columns]
    remaining = [c for c in scored.columns if c not in present_master]
    scored = scored[present_master + remaining]

    unmatched = (
        pd.concat(unmatched_frames, ignore_index=True) if unmatched_frames else pd.DataFrame()
    )

    return PipelineResult(scored=scored, unmatched=unmatched, warnings=warnings)
