"""Per-URL recommendation builder.

Turns one scored row into the eight-field recommendation the report spec
requires: URL, bucket, priority score, primary issue, evidence, recommended
action, implementation owner, and confidence.

The evidence list is the core of the project's "cite the fields that caused it"
principle. Every evidence line references an actual field and value from the
row, so a reader can audit why a page landed in its bucket rather than trusting
an opaque label. Missing values are skipped rather than invented.
"""

from __future__ import annotations

from ppi.scoring.components import _num

# Who typically owns the work for each bucket.
_OWNER_BY_BUCKET = {
    "Fix Now": "SEO and development",
    "Performance Fix": "Development",
    "Quick Win": "SEO and content",
    "Refresh/Expand": "Content",
    "Internal Link Push": "SEO and content",
    "Authority Gap": "SEO and offsite outreach",
    "Protect": "SEO and analytics",
    "Merge/Prune": "SEO and content",
    "Monitor": "Analytics",
}

# Thresholds reused from the bucket layer for phrasing evidence.
_THIN_WORDS = 300
_DEEP_DEPTH = 4
_LOW_ENGAGEMENT = 0.50


def _fmt_int(value: object) -> str:
    n = _num(value)
    return f"{int(n):,}" if n is not None else ""


def _fmt_float(value: object, places: int = 2) -> str:
    n = _num(value)
    return f"{n:.{places}f}" if n is not None else ""


def _fmt_pct(value: object) -> str:
    n = _num(value)
    return f"{n * 100:.2f}%" if n is not None else ""


def primary_issue(row: dict) -> str:
    """Return a one-line diagnosis tailored to the row's bucket and values."""
    bucket = row.get("recommendation_bucket", "Monitor")
    position = _fmt_float(row.get("gsc_avg_position"), 1)
    impressions = _fmt_int(row.get("gsc_impressions"))

    if bucket == "Fix Now":
        status = _num(row.get("status_code"))
        if status is not None and int(status) != 200:
            return (
                f"Returns HTTP {int(status)} while still receiving "
                f"{impressions or 'search'} impressions, so it cannot perform."
            )
        return (
            "A serious technical blocker (indexability, robots, or canonical) is "
            "preventing this page from performing despite existing demand."
        )
    if bucket == "Performance Fix":
        return (
            "Core Web Vitals are in the poor range on a page that carries traffic, "
            "conversions, or search demand, which suppresses its results."
        )
    if bucket == "Quick Win":
        return (
            f"Ranks around position {position or 'in striking distance'} with "
            f"{impressions or 'meaningful'} impressions, but CTR is below the "
            "expected rate for its ranking band."
        )
    if bucket == "Refresh/Expand":
        return (
            "Has search demand but weak content or engagement signals, so it is "
            "underperforming its potential."
        )
    if bucket == "Internal Link Push":
        return (
            "Has demand but weak internal linking or excessive crawl depth, "
            "limiting how much authority flows to it."
        )
    if bucket == "Authority Gap":
        return (
            "Has demand but thin external authority relative to the rest of the "
            "site, capping how high it can rank."
        )
    if bucket == "Protect":
        return (
            "Already performs and converts well with no major issues; the risk "
            "here is losing ground, not failing to gain it."
        )
    if bucket == "Merge/Prune":
        return (
            "Low across impressions, clicks, sessions, links, and content, so it "
            "adds little and may dilute the site."
        )
    return (
        "No strong signal yet, or insufficient data to justify a specific action."
    )


def gather_evidence(row: dict, limit: int = 6) -> list[str]:
    """Collect up to `limit` evidence lines, each citing a real field and value."""
    lines: list[str] = []

    # Technical facts.
    status = _num(row.get("status_code"))
    if status is not None:
        lines.append(f"HTTP status code is {int(status)}.")
    indexability = str(row.get("indexability") or "").strip()
    if indexability and indexability.lower().startswith("non"):
        reason = str(row.get("indexability_status") or "").strip()
        lines.append(
            f"Marked non-indexable{f' ({reason})' if reason else ''}."
        )
    if row.get("canonical_match") is False:
        lines.append("Google-selected canonical differs from the declared canonical.")

    # Demand and CTR.
    impressions = _fmt_int(row.get("gsc_impressions"))
    if impressions:
        lines.append(f"Search impressions: {impressions}.")
    position = _fmt_float(row.get("gsc_avg_position"), 1)
    if position:
        lines.append(f"Average position: {position}.")
    if _num(row.get("ctr_gap_score")) and _num(row.get("ctr_gap_score")) >= 0.30:
        ctr = _fmt_pct(row.get("gsc_ctr"))
        lines.append(
            f"CTR{f' ({ctr})' if ctr else ''} is below the expected rate for its "
            "ranking band."
        )

    # Engagement and value.
    sessions = _fmt_int(row.get("ga4_sessions"))
    if sessions:
        lines.append(f"GA4 sessions: {sessions}.")
    conversions = _fmt_int(row.get("ga4_conversions"))
    if conversions:
        lines.append(f"GA4 conversions: {conversions}.")
    engagement = _num(row.get("ga4_engagement_rate"))
    if engagement is not None and engagement < _LOW_ENGAGEMENT:
        lines.append(f"Engagement rate is low ({engagement:.2f}).")

    # Authority and structure.
    if _num(row.get("referring_domain_gap")) and _num(row.get("referring_domain_gap")) >= 0.60:
        ref = _fmt_int(row.get("referring_domains"))
        lines.append(
            f"Referring domains{f' ({ref})' if ref else ''} are below the site benchmark."
        )
    if _num(row.get("internal_link_gap")) and _num(row.get("internal_link_gap")) >= 0.60:
        inl = _fmt_int(row.get("inlinks"))
        lines.append(
            f"Internal inlinks{f' ({inl})' if inl else ''} are below the site benchmark."
        )
    depth = _num(row.get("crawl_depth"))
    if depth is not None and depth > _DEEP_DEPTH:
        lines.append(f"Crawl depth is {int(depth)} (deep).")

    # Content and performance.
    words = _num(row.get("word_count"))
    if words is not None and words < _THIN_WORDS:
        lines.append(f"Word count is {int(words)} (thin).")
    lcp = _fmt_float(row.get("psi_lcp"), 1)
    inp = _fmt_int(row.get("psi_inp"))
    cls = _fmt_float(row.get("psi_cls"), 2)
    if lcp or inp or cls:
        parts = []
        if lcp:
            parts.append(f"LCP {lcp}s")
        if inp:
            parts.append(f"INP {inp}ms")
        if cls:
            parts.append(f"CLS {cls}")
        lines.append("Core Web Vitals: " + ", ".join(parts) + ".")

    if not lines:
        lines.append("Insufficient data; limited fields were available for this URL.")
    return lines[:limit]


def build_recommendation(row: dict) -> dict:
    """Return the full eight-field recommendation for one scored row."""
    bucket = row.get("recommendation_bucket", "Monitor")
    return {
        "url": row.get("url", ""),
        "bucket": bucket,
        "priority_score": row.get("priority_score", 0.0),
        "primary_issue": primary_issue(row),
        "evidence": gather_evidence(row),
        "recommended_action": row.get(
            "primary_recommendation", "Keep under review."
        ),
        "implementation_owner": _OWNER_BY_BUCKET.get(bucket, "SEO"),
        "confidence": row.get("confidence_score", "Low"),
    }
