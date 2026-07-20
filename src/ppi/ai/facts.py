"""Structured fact extraction and prompt construction for the AI writer.

Only a small, structured set of per-URL facts is ever sent to a provider:
identifiers, the already-computed score and bucket, the metrics that are present,
evidence flags, and an explicit list of which metrics are missing. Raw datasets,
full uploads, and any field not listed here are never sent. This is the boundary
that keeps the AI layer compliant with the privacy rules.
"""

from __future__ import annotations

import json

from ppi.reporting.recommendations import gather_evidence
from ppi.scoring.components import _num

# Per-URL metrics that may be shared as structured facts. Nothing else is sent.
_METRIC_FIELDS = [
    "status_code",
    "indexability",
    "gsc_impressions",
    "gsc_clicks",
    "gsc_ctr",
    "gsc_avg_position",
    "ga4_sessions",
    "ga4_conversions",
    "referring_domains",
    "inlinks",
    "crawl_depth",
    "word_count",
    "psi_lcp",
    "psi_inp",
    "psi_cls",
]


def build_facts(row: dict) -> dict:
    """Return only the structured facts that may be sent to a provider.

    The result contains the URL, the authoritative bucket and priority score
    (which the AI must not change), the metrics that are present, evidence flags
    derived from the row, and a list of metrics that are missing so the AI knows
    not to reference them.
    """
    metrics: dict[str, object] = {}
    missing: list[str] = []
    for field in _METRIC_FIELDS:
        value = row.get(field)
        num = _num(value)
        if num is not None:
            metrics[field] = num
        elif isinstance(value, str) and value.strip():
            metrics[field] = value.strip()
        else:
            missing.append(field)

    return {
        "url": row.get("url", ""),
        "bucket": row.get("recommendation_bucket", "Monitor"),
        "priority_score": row.get("priority_score", 0.0),
        "metrics": metrics,
        "evidence_flags": gather_evidence(row),
        "missing_data": missing,
        "confidence": row.get("confidence_score", "Low"),
    }


SYSTEM_PROMPT = (
    "You are an SEO assistant that writes clear, stakeholder-facing recommendations "
    "from structured facts. Strict rules: "
    "1. Do not calculate, change, or second-guess the priority score or bucket; "
    "use the values given. "
    "2. Use only the facts provided. Do not invent metrics, numbers, or claims. "
    "3. If a metric appears in missing_data, do not reference it or guess it. "
    "4. Tie every recommended action to the evidence provided. "
    "5. Do not promise rankings, traffic, or revenue. Do not exaggerate impact. "
    "6. Lower the confidence value when data is missing. "
    "7. implementation_owner must be one of: SEO, Content, Developer, Analytics, "
    "Security, Site Owner, Mixed. "
    "Return ONLY a single JSON object matching the requested schema, with no "
    "surrounding text, no markdown, and no code fences."
)

_SCHEMA_HINT = {
    "url": "",
    "bucket": "",
    "priority_score": 0,
    "primary_issue": "",
    "evidence": [],
    "recommended_actions": [],
    "risk_level": "",
    "implementation_owner": "",
    "confidence": "",
}


def build_user_prompt(facts: dict) -> str:
    """Build the user prompt: the facts plus the required output schema."""
    return (
        "Structured facts for one URL:\n"
        + json.dumps(facts, ensure_ascii=False)
        + "\n\nReturn a JSON object with exactly these keys:\n"
        + json.dumps(_SCHEMA_HINT, ensure_ascii=False)
        + "\n\nKeep url, bucket, and priority_score identical to the facts. "
        "risk_level must be one of: High, Medium, Low."
    )
