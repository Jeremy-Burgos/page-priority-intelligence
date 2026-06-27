"""Screaming Frog Internal All CSV ingestion.

Maps the Internal All export onto ScreamingFrogRow fields and attaches a
normalized_url for joining. Screaming Frog is treated as the crawl backbone:
the set of URLs it returns is usually the base universe for the report.
"""

from __future__ import annotations

import pandas as pd

from ppi.ingestion.base import (
    check_expected_columns,
    map_columns,
    read_csv_flexible,
)
from ppi.normalization.url_tools import normalize_url
from ppi.schemas.inputs import ScreamingFrogRow

# Clean field -> acceptable source headers (covers common version differences).
_COLUMN_MAP = {
    "url": ["Address", "URL", "url"],
    "status_code": ["Status Code", "status_code"],
    "status": ["Status", "status"],
    "indexability": ["Indexability", "indexability"],
    "indexability_status": ["Indexability Status", "indexability_status"],
    "title": ["Title 1", "Title", "title"],
    "title_length": ["Title 1 Length", "Title Length", "title_length"],
    "meta_description": ["Meta Description 1", "Meta Description", "meta_description"],
    "meta_description_length": [
        "Meta Description 1 Length",
        "Meta Description Length",
        "meta_description_length",
    ],
    "h1": ["H1-1", "H1", "h1"],
    "word_count": ["Word Count", "word_count"],
    "canonical_link_element": [
        "Canonical Link Element 1",
        "Canonical Link Element",
        "canonical_link_element",
    ],
    "inlinks": ["Inlinks", "inlinks"],
    "unique_inlinks": ["Unique Inlinks", "unique_inlinks"],
    "crawl_depth": ["Crawl Depth", "crawl_depth"],
}

_REQUIRED_FIELDS = {"indexability", "status_code", "url"}
_EXPECTED_FIELDS = {"crawl_depth", "inlinks", "title", "word_count"}


def load_screaming_frog(source: object, warnings: list[str] | None = None) -> pd.DataFrame:
    """Load a Screaming Frog Internal All export into a clean DataFrame.

    Args:
        source: Path, bytes, or file-like object for the CSV.
        warnings: Optional list to collect data quality warnings about
            missing required or expected columns. Not raised, just recorded.

    Returns:
        A DataFrame of validated rows with an added normalized_url column.
        Rows without a usable URL are dropped (they cannot be joined).
    """
    raw = read_csv_flexible(source)
    mapped = map_columns(raw, _COLUMN_MAP)
    check_expected_columns(
        raw,
        _COLUMN_MAP,
        "Screaming Frog",
        _REQUIRED_FIELDS,
        _EXPECTED_FIELDS,
        warnings,
    )

    records: list[dict] = []
    for row in mapped.to_dict(orient="records"):
        if not row.get("url"):
            continue
        validated = ScreamingFrogRow(**row)
        record = validated.model_dump()
        record["normalized_url"] = normalize_url(record["url"])
        records.append(record)

    return pd.DataFrame(records)
