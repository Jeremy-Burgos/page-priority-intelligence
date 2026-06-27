"""URL Inspection CSV ingestion.

Maps a URL Inspection export onto UrlInspectionRow fields and derives a
canonical_match flag by comparing the Google-selected canonical against the
user-declared canonical after normalization.
"""

from __future__ import annotations

import pandas as pd

from ppi.ingestion.base import (
    check_expected_columns,
    map_columns,
    read_csv_flexible,
)
from ppi.normalization.url_tools import normalize_url
from ppi.schemas.inputs import UrlInspectionRow

_COLUMN_MAP = {
    "url": ["Inspection URL", "URL", "url"],
    "url_inspection_index_status": ["Index status", "Verdict", "url_inspection_index_status"],
    "url_inspection_coverage_state": ["Coverage state", "Coverage", "url_inspection_coverage_state"],
    "url_inspection_robots_state": ["Robots state", "url_inspection_robots_state"],
    "url_inspection_last_crawl": ["Last crawl", "url_inspection_last_crawl"],
    "url_inspection_google_canonical": ["Google-selected canonical", "url_inspection_google_canonical"],
    "url_inspection_user_canonical": ["User-declared canonical", "url_inspection_user_canonical"],
    "url_inspection_sitemap_presence": ["Sitemap presence", "Sitemap", "url_inspection_sitemap_presence"],
}

_REQUIRED_FIELDS = {"url"}
_EXPECTED_FIELDS = {"url_inspection_coverage_state", "url_inspection_google_canonical", "url_inspection_user_canonical"}


def load_url_inspection(source: object, warnings: list[str] | None = None) -> pd.DataFrame:
    """Load a URL Inspection export into a clean DataFrame.

    Args:
        source: Path, bytes, or file-like object for the CSV.
        warnings: Optional list to collect data quality warnings about
            missing required or expected columns. Not raised, just recorded.

    Returns:
        A DataFrame of validated rows with normalized_url and a derived
        canonical_match boolean. Rows without a usable URL are dropped.
    """
    raw = read_csv_flexible(source)
    mapped = map_columns(raw, _COLUMN_MAP)
    check_expected_columns(
        raw,
        _COLUMN_MAP,
        "URL Inspection",
        _REQUIRED_FIELDS,
        _EXPECTED_FIELDS,
        warnings,
    )

    records: list[dict] = []
    for row in mapped.to_dict(orient="records"):
        if not row.get("url"):
            continue
        validated = UrlInspectionRow(**row)
        record = validated.model_dump()
        record["normalized_url"] = normalize_url(record["url"])

        google_canonical = record.get("url_inspection_google_canonical")
        user_canonical = record.get("url_inspection_user_canonical")
        if google_canonical and user_canonical:
            record["canonical_match"] = (
                normalize_url(google_canonical) == normalize_url(user_canonical)
            )
        else:
            record["canonical_match"] = None
        records.append(record)

    return pd.DataFrame(records)
