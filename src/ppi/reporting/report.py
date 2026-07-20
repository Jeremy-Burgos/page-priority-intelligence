"""Markdown and HTML stakeholder report builders.

These turn a scored DataFrame into the two stakeholder-facing reports described in
the report output spec. Both reports are built entirely in memory from data the
caller already has; nothing is written to disk here. The HTML report escapes all
dynamic content so a URL or title containing markup cannot break the page.

The two builders share the same section structure so the HTML and Markdown
reports stay consistent:
  1. Executive summary
  2. Data sources used
  3. Data quality warnings
  4. Top priority URLs
  5. One section per recommendation bucket
  6. Methodology and scoring explanation
  7. Next steps
"""

from __future__ import annotations

import html
from datetime import date

import pandas as pd

from ppi.reporting.recommendations import build_recommendation

DISCLAIMER = (
    "This tool prioritizes SEO work based on available data. It does not "
    "guarantee rankings, traffic, conversions, or indexing."
)

# Buckets in the order they should appear in the report (matches the spec's
# section order). Monitor is appended last so no URL is omitted.
BUCKET_ORDER = [
    "Fix Now",
    "Quick Win",
    "Refresh/Expand",
    "Internal Link Push",
    "Authority Gap",
    "Performance Fix",
    "Merge/Prune",
    "Protect",
    "Monitor",
]

# Section headings that differ from "<bucket> URLs".
_SECTION_HEADING = {
    "Merge/Prune": "Merge/Prune Candidates",
}


def _section_heading(bucket: str, count: int) -> str:
    base = _SECTION_HEADING.get(bucket, f"{bucket} URLs")
    return f"{base} ({count})"

_TABLE_COLUMNS = [
    ("url", "URL"),
    ("priority_score", "Priority"),
    ("recommendation_bucket", "Bucket"),
    ("confidence_score", "Confidence"),
    ("primary_recommendation", "Recommended action"),
]

_METHODOLOGY = (
    "Each URL is scored across six weighted components: SEO opportunity (search "
    "demand multiplied by underperformance), technical risk opportunity (demand "
    "multiplied by technical risk), authority and internal link gap, performance "
    "risk opportunity (traffic value multiplied by Core Web Vitals risk), decay "
    "risk, and business value. Skewed metrics such as impressions, clicks, "
    "sessions, and referring domains are log-scaled against the site's 90th "
    "percentile rather than averaged, so a few outliers do not dominate. Each URL "
    "is then assigned one recommendation bucket using a priority-ordered rule set."
)

_SCORING_NOTE = (
    "The priority score is a relative ranking signal from 0 to 100, not an "
    "absolute grade. Use it to decide the order of work, not as a measure of how "
    "good a page is. A confidence level accompanies every URL and reflects how "
    "many independent data sources backed that row."
)


def _sources_line(sources_used: list[str]) -> str:
    if not sources_used:
        return "No sources recorded."
    return ", ".join(sources_used)


def _bucket_counts(scored: pd.DataFrame) -> dict[str, int]:
    counts = scored["recommendation_bucket"].value_counts().to_dict()
    return {b: int(counts.get(b, 0)) for b in BUCKET_ORDER}


def _rows_for_bucket(scored: pd.DataFrame, bucket: str, limit: int = 50) -> pd.DataFrame:
    subset = scored[scored["recommendation_bucket"] == bucket]
    return subset.head(limit)


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def _md_escape_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _md_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No URLs in this bucket._\n"
    headers = [label for _, label in _TABLE_COLUMNS]
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for record in frame.to_dict(orient="records"):
        cells = [_md_escape_cell(record.get(key, "")) for key, _ in _TABLE_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _md_recommendation_block(rec: dict) -> str:
    """Render one URL's full eight-field recommendation in Markdown."""
    evidence = "\n".join(f"  - {_md_escape_cell(e)}" for e in rec["evidence"])
    return (
        f"**{_md_escape_cell(rec['url'])}**\n"
        f"- Bucket: {_md_escape_cell(rec['bucket'])}\n"
        f"- Priority score: {_md_escape_cell(rec['priority_score'])}\n"
        f"- Primary issue: {_md_escape_cell(rec['primary_issue'])}\n"
        f"- Evidence:\n{evidence}\n"
        f"- Recommended action: {_md_escape_cell(rec['recommended_action'])}\n"
        f"- Implementation owner: {_md_escape_cell(rec['implementation_owner'])}\n"
        f"- Confidence: {_md_escape_cell(rec['confidence'])}\n"
    )


def _md_bucket_section(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No URLs in this bucket._\n"
    blocks = [_md_recommendation_block(build_recommendation(r)) for r in frame.to_dict(orient="records")]
    return "\n".join(blocks)


def build_markdown_report(
    scored: pd.DataFrame,
    warnings: list[str] | None = None,
    sources_used: list[str] | None = None,
    top_n: int = 10,
) -> str:
    """Build the stakeholder-facing Markdown report as a string."""
    warnings = warnings or []
    sources_used = sources_used or []
    counts = _bucket_counts(scored)
    total = len(scored)

    parts: list[str] = []
    parts.append("# Page Priority Intelligence Report")
    parts.append(f"_Generated {date.today().isoformat()}._\n")

    # 1. Executive summary
    parts.append("## Executive Summary")
    parts.append(
        f"{total} URLs were scored and prioritized. "
        f"{counts['Fix Now']} need immediate technical fixes, "
        f"{counts['Quick Win']} are quick wins, and "
        f"{counts['Performance Fix']} need performance work. "
        "The tables below group every URL by recommended action, ordered by "
        "priority score within each group.\n"
    )

    # 2. Data sources used
    parts.append("## Data Sources Used")
    parts.append(_sources_line(sources_used) + "\n")

    # 3. Data quality warnings
    parts.append("## Data Quality Warnings")
    if warnings:
        parts.append("\n".join(f"- {_md_escape_cell(w)}" for w in warnings) + "\n")
    else:
        parts.append("No data quality warnings were raised.\n")

    # 4. Top priority URLs
    parts.append(f"## Top {top_n} Priority URLs")
    parts.append(_md_table(scored.head(top_n)))

    # 5. One section per bucket, each URL rendered as a full recommendation.
    for bucket in BUCKET_ORDER:
        parts.append(f"## {_section_heading(bucket, counts[bucket])}")
        parts.append(_md_bucket_section(_rows_for_bucket(scored, bucket)))

    # 6. Methodology and scoring explanation
    parts.append("## Methodology")
    parts.append(_METHODOLOGY + "\n")
    parts.append("## Scoring Explanation")
    parts.append(_SCORING_NOTE + "\n")

    # 7. Next steps
    parts.append("## Next Steps")
    parts.append(
        "1. Resolve Fix Now URLs first; technical blockers prevent every other "
        "gain.\n"
        "2. Ship Quick Win title and meta description changes for fast CTR "
        "recovery.\n"
        "3. Schedule Performance Fix and Refresh/Expand work by priority score.\n"
        "4. Review Merge/Prune candidates before investing further in them.\n"
    )

    parts.append("---")
    parts.append(f"_{DISCLAIMER}_")

    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def _h(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _html_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "<p class='empty'>No URLs in this bucket.</p>"
    head = "".join(f"<th>{_h(label)}</th>" for _, label in _TABLE_COLUMNS)
    body_rows = []
    for record in frame.to_dict(orient="records"):
        cells = "".join(f"<td>{_h(record.get(key, ''))}</td>" for key, _ in _TABLE_COLUMNS)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _html_recommendation_block(rec: dict) -> str:
    """Render one URL's full eight-field recommendation as an HTML block."""
    evidence = "".join(f"<li>{_h(e)}</li>" for e in rec["evidence"])
    return (
        "<div class='rec'>"
        f"<div class='rec-url'>{_h(rec['url'])}</div>"
        "<dl>"
        f"<dt>Bucket</dt><dd>{_h(rec['bucket'])}</dd>"
        f"<dt>Priority score</dt><dd>{_h(rec['priority_score'])}</dd>"
        f"<dt>Primary issue</dt><dd>{_h(rec['primary_issue'])}</dd>"
        f"<dt>Evidence</dt><dd><ul>{evidence}</ul></dd>"
        f"<dt>Recommended action</dt><dd>{_h(rec['recommended_action'])}</dd>"
        f"<dt>Implementation owner</dt><dd>{_h(rec['implementation_owner'])}</dd>"
        f"<dt>Confidence</dt><dd>{_h(rec['confidence'])}</dd>"
        "</dl></div>"
    )


def _html_bucket_section(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "<p class='empty'>No URLs in this bucket.</p>"
    return "".join(
        _html_recommendation_block(build_recommendation(r))
        for r in frame.to_dict(orient="records")
    )


def _card(label: str, value: int) -> str:
    return (
        f"<div class='card'><div class='card-value'>{value}</div>"
        f"<div class='card-label'>{_h(label)}</div></div>"
    )


def build_html_report(
    scored: pd.DataFrame,
    warnings: list[str] | None = None,
    sources_used: list[str] | None = None,
    top_n: int = 10,
) -> str:
    """Build the stakeholder-facing HTML report as a self-contained string."""
    warnings = warnings or []
    sources_used = sources_used or []
    counts = _bucket_counts(scored)
    total = len(scored)

    cards = "".join(
        [
            _card("URLs scored", total),
            _card("Fix Now", counts["Fix Now"]),
            _card("Quick Win", counts["Quick Win"]),
            _card("Performance Fix", counts["Performance Fix"]),
        ]
    )

    if warnings:
        warnings_html = "<ul>" + "".join(f"<li>{_h(w)}</li>" for w in warnings) + "</ul>"
    else:
        warnings_html = "<p>No data quality warnings were raised.</p>"

    bucket_sections = []
    for bucket in BUCKET_ORDER:
        heading = _SECTION_HEADING.get(bucket, f"{bucket} URLs")
        bucket_sections.append(
            f"<h2>{_h(heading)} <span class='count'>({counts[bucket]})</span></h2>"
            + _html_bucket_section(_rows_for_bucket(scored, bucket))
        )

    style = (
        "body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
        "color:#1a1a1a;max-width:1100px;margin:0 auto;padding:24px;line-height:1.5}"
        "h1{margin-bottom:4px}h2{margin-top:32px;border-bottom:2px solid #eee;padding-bottom:6px}"
        ".cards{display:flex;gap:16px;flex-wrap:wrap;margin:20px 0}"
        ".card{flex:1;min-width:140px;background:#f6f8fa;border:1px solid #e2e6ea;"
        "border-radius:8px;padding:16px;text-align:center}"
        ".card-value{font-size:30px;font-weight:700}.card-label{color:#555;font-size:13px}"
        "table{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}"
        "th,td{border:1px solid #e2e6ea;padding:8px;text-align:left;vertical-align:top}"
        "th{background:#f6f8fa}.empty{color:#777;font-style:italic}"
        ".count{color:#777;font-weight:400;font-size:15px}"
        ".rec{border:1px solid #e2e6ea;border-radius:8px;padding:14px 16px;margin:12px 0;background:#fff}"
        ".rec-url{font-weight:700;word-break:break-all;margin-bottom:8px}"
        ".rec dl{display:grid;grid-template-columns:160px 1fr;gap:4px 14px;margin:0}"
        ".rec dt{font-weight:600;color:#555}.rec dd{margin:0}"
        ".rec ul{margin:0;padding-left:18px}"
        ".disclaimer{margin-top:32px;padding:14px;background:#fff8e6;border:1px solid #f0d98a;"
        "border-radius:8px;font-size:13px}"
    )

    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Page Priority Intelligence Report</title><style>{style}</style></head>"
        "<body>"
        "<h1>Page Priority Intelligence Report</h1>"
        f"<p>Generated {_h(date.today().isoformat())}.</p>"
        "<h2>Executive Summary</h2>"
        f"<div class='cards'>{cards}</div>"
        f"<p>{total} URLs were scored and prioritized. The sections below group "
        "every URL by recommended action, ordered by priority score.</p>"
        "<h2>Data Sources Used</h2>"
        f"<p>{_h(_sources_line(sources_used))}</p>"
        "<h2>Data Quality Warnings</h2>"
        f"{warnings_html}"
        f"<h2>Top {top_n} Priority URLs</h2>"
        f"{_html_table(scored.head(top_n))}"
        + "".join(bucket_sections)
        + "<h2>Methodology</h2>"
        f"<p>{_h(_METHODOLOGY)}</p>"
        "<h2>Scoring Explanation</h2>"
        f"<p>{_h(_SCORING_NOTE)}</p>"
        "<h2>Next Steps</h2>"
        "<ol>"
        "<li>Resolve Fix Now URLs first; technical blockers prevent every other gain.</li>"
        "<li>Ship Quick Win title and meta description changes for fast CTR recovery.</li>"
        "<li>Schedule Performance Fix and Refresh/Expand work by priority score.</li>"
        "<li>Review Merge/Prune candidates before investing further in them.</li>"
        "</ol>"
        f"<div class='disclaimer'>{_h(DISCLAIMER)}</div>"
        "</body></html>"
    )
