"""Google Search Console Pages CSV ingestion.

Maps a GSC Pages export onto GscRow fields and attaches a normalized_url.
"""

from __future__ import annotations

import pandas as pd

from ppi.ingestion.base import (
    check_expected_columns,
    map_columns,
    read_csv_flexible,
)
from ppi.normalization.url_tools import normalize_url
from ppi.schemas.inputs import GscRow

_COLUMN_MAP = {
    "url": ["Page", "Top pages", "URL", "url"],
    "gsc_clicks": ["Clicks", "gsc_clicks"],
    "gsc_impressions": ["Impressions", "gsc_impressions"],
    "gsc_ctr": ["CTR", "gsc_ctr"],
    "gsc_avg_position": ["Position", "Average Position", "gsc_avg_position"],
    "gsc_query_count": ["Queries", "Query Count", "gsc_query_count"],
}

_REQUIRED_FIELDS = {"url"}
_EXPECTED_FIELDS = {"gsc_avg_position", "gsc_clicks", "gsc_ctr", "gsc_impressions"}


def load_gsc(source: object, warnings: list[str] | None = None) -> pd.DataFrame:
    """Load a GSC Pages export into a clean DataFrame.

    Args:
        source: Path, bytes, or file-like object for the CSV.
        warnings: Optional list to collect data quality warnings about
            missing required or expected columns. Not raised, just recorded.

    Returns:
        A DataFrame of validated rows with an added normalized_url column.
        Rows without a usable URL are dropped.
    """
    raw = read_csv_flexible(source)
    mapped = map_columns(raw, _COLUMN_MAP)
    check_expected_columns(
        raw,
        _COLUMN_MAP,
        "Search Console",
        _REQUIRED_FIELDS,
        _EXPECTED_FIELDS,
        warnings,
    )

    records: list[dict] = []
    for row in mapped.to_dict(orient="records"):
        if not row.get("url"):
            continue
        validated = GscRow(**row)
        record = validated.model_dump()
        record["normalized_url"] = normalize_url(record["url"])
        records.append(record)

    return pd.DataFrame(records)
