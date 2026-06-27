"""Backlink CSV ingestion (Ahrefs, Semrush, or manual exports).

Maps a backlink export onto BacklinkRow fields. Referring domains are the more
trustworthy authority signal than raw backlink counts, which the scoring layer
weights accordingly.
"""

from __future__ import annotations

import pandas as pd

from ppi.ingestion.base import (
    check_expected_columns,
    map_columns,
    read_csv_flexible,
)
from ppi.normalization.url_tools import normalize_url
from ppi.schemas.inputs import BacklinkRow

_COLUMN_MAP = {
    "url": ["URL", "Target URL", "Page", "url"],
    "backlinks": ["Backlinks", "backlinks"],
    "referring_domains": ["Referring domains", "Ref domains", "referring_domains"],
    "authority_score": ["Authority score", "Domain Rating", "Page Authority", "authority_score"],
    "backlink_source": ["Source", "backlink_source"],
}

_REQUIRED_FIELDS = {"url"}
_EXPECTED_FIELDS = {"backlinks", "referring_domains"}


def load_backlinks(source: object, warnings: list[str] | None = None) -> pd.DataFrame:
    """Load a backlink export into a clean DataFrame.

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
        "Backlinks",
        _REQUIRED_FIELDS,
        _EXPECTED_FIELDS,
        warnings,
    )

    records: list[dict] = []
    for row in mapped.to_dict(orient="records"):
        if not row.get("url"):
            continue
        validated = BacklinkRow(**row)
        record = validated.model_dump()
        record["normalized_url"] = normalize_url(record["url"])
        records.append(record)

    return pd.DataFrame(records)
