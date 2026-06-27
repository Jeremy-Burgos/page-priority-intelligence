"""Shared ingestion helpers.

Each source reader maps that source's real (and often inconsistent) column
headers onto the clean field names defined in schemas/inputs.py, validates each
row, and returns a tidy DataFrame. The header matching is intentionally lenient
because tools rename columns between versions and locales.
"""

from __future__ import annotations

import io
from typing import Optional

import pandas as pd


def read_csv_flexible(source: object) -> pd.DataFrame:
    """Read a CSV from a path, bytes, or file-like object into a DataFrame.

    Everything is read as string first so that pydantic validators control all
    type coercion. This keeps "0", "0.0", and "" from being silently reinterpreted
    by pandas in inconsistent ways.

    Args:
        source: A filesystem path, a bytes object, or a file-like object such
            as the upload returned by Streamlit.

    Returns:
        A DataFrame with all columns as strings and stripped header names.
    """
    if isinstance(source, (bytes, bytearray)):
        buffer = io.BytesIO(source)
        frame = pd.read_csv(buffer, dtype=str, keep_default_na=False)
    else:
        frame = pd.read_csv(source, dtype=str, keep_default_na=False)

    frame.columns = [str(col).strip() for col in frame.columns]
    return frame


def _normalize_header(name: str) -> str:
    """Reduce a header to a comparison key: lowercase, alphanumeric only."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def find_column(frame: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    """Return the first DataFrame column matching any candidate name.

    Matching ignores case, spaces, and punctuation, so "Avg. Position",
    "average_position", and "Position" can all resolve to the same field.

    Args:
        frame: The source DataFrame.
        candidates: Acceptable header names in priority order.

    Returns:
        The actual column name present in the frame, or None if no match.
    """
    lookup = {_normalize_header(col): col for col in frame.columns}
    for candidate in candidates:
        key = _normalize_header(candidate)
        if key in lookup:
            return lookup[key]
    return None


def check_expected_columns(
    frame: pd.DataFrame,
    mapping: dict[str, list[str]],
    source_label: str,
    required: set[str],
    expected: set[str],
    warnings: Optional[list[str]] = None,
) -> dict[str, list[str]]:
    """Detect missing required and expected columns and record warnings.

    This is how requirement 3 (validate required columns) and requirement 6
    (warn on missing expected columns) are satisfied without failing hard. A
    missing required column produces a severe warning because the source cannot
    do its job. A missing expected column produces a softer warning because the
    source is still usable but some scores will degrade.

    Args:
        frame: The raw source DataFrame.
        mapping: Clean field name -> acceptable source headers (same mapping
            used by map_columns).
        source_label: Human-readable source name for the warning text.
        required: Clean field names that must be present for the source to be
            meaningful (for example, the URL column).
        expected: Clean field names that should normally be present and feed
            scoring, but whose absence is not fatal.
        warnings: Optional list to append readable warning strings to. The same
            accumulator the pipeline uses, so ingestion and join warnings end up
            in one place. If None, warnings are still returned in the result.

    Returns:
        A dict with keys "missing_required" and "missing_expected", each a list
        of the clean field names that could not be resolved to a column.
    """
    missing_required: list[str] = []
    missing_expected: list[str] = []

    for field in sorted(required):
        candidates = mapping.get(field, [field])
        if find_column(frame, candidates) is None:
            missing_required.append(field)

    for field in sorted(expected):
        candidates = mapping.get(field, [field])
        if find_column(frame, candidates) is None:
            missing_expected.append(field)

    if warnings is not None:
        for field in missing_required:
            accepted = ", ".join(mapping.get(field, [field]))
            warnings.append(
                f"{source_label}: required column for '{field}' was not found "
                f"(expected one of: {accepted}). Rows from this source may be "
                f"unusable or dropped."
            )
        for field in missing_expected:
            accepted = ", ".join(mapping.get(field, [field]))
            warnings.append(
                f"{source_label}: expected column for '{field}' was not found "
                f"(expected one of: {accepted}). Scores that rely on it will be "
                f"reduced and confidence may drop."
            )

    return {
        "missing_required": missing_required,
        "missing_expected": missing_expected,
    }


def map_columns(frame: pd.DataFrame, mapping: dict[str, list[str]]) -> pd.DataFrame:
    """Build a new DataFrame keyed by clean field names.

    Args:
        frame: The raw source DataFrame.
        mapping: Clean field name -> list of acceptable source headers.

    Returns:
        A DataFrame whose columns are the clean field names. Fields whose source
        column is absent are filled with None so downstream code can treat them
        as missing rather than crashing.
    """
    data: dict[str, object] = {}
    for clean_name, candidates in mapping.items():
        actual = find_column(frame, candidates)
        data[clean_name] = frame[actual] if actual is not None else None
    return pd.DataFrame(data, index=frame.index)
