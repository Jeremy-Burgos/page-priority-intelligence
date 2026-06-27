"""URL normalization and dataset joining helpers.

Every dataset (crawl, Search Console, GA4, PageSpeed, URL Inspection, backlinks)
reports URLs slightly differently. Before any join can be trusted, URLs must be
reduced to a single canonical form. These helpers implement the rules defined in
the project's URL normalization spec.

Design choices:
  - Scheme and host are lowercased.
  - Fragments (#...) are removed.
  - Known tracking parameters are stripped; remaining query params are kept and
    sorted so order does not affect matching, unless query preservation is
    turned off by configuration.
  - A single trailing slash is normalized consistently (kept on directory-style
    paths, not added to paths that look like files).
  - The original input is always preserved as source_url so nothing is lost.
  - HTTP can optionally be rewritten to HTTPS when the caller configures it.

Two public entry points exist:
  - normalize_url returns a plain canonical string. This is the low-level
    primitive that the ingestion readers call.
  - normalize_url_record returns a structured dict that also preserves the
    source URL and reports a match-confidence judgement, for callers that need
    to track how reliable each join key is.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ppi.config import TRACKING_PARAMS


@dataclass(frozen=True)
class NormalizeOptions:
    """Configuration for how a URL is normalized.

    Attributes:
        force_https: When True, an http scheme is rewritten to https. Off by
            default because forcing the scheme can create a false match when a
            site genuinely serves different content on http and https. Turn it
            on only when you know the site canonicalizes to https.
        keep_query: When True (default), non-tracking query parameters are kept
            and sorted. When False, the entire query string is dropped, which is
            useful for sites where query parameters never change the page.
    """

    force_https: bool = False
    keep_query: bool = True


DEFAULT_OPTIONS = NormalizeOptions()


def normalize_url(raw_url: str, options: NormalizeOptions | None = None) -> str:
    """Return a canonical form of a URL suitable for joining datasets.

    The transformation is deterministic. The original value is not part of the
    return; callers that need it should use normalize_url_record or store the
    input themselves as source_url.

    Args:
        raw_url: A URL string from any source export. May contain campaign
            tags, mixed case host, fragments, or inconsistent trailing slashes.
        options: Optional NormalizeOptions controlling scheme forcing and query
            handling. Defaults to no scheme forcing and query preservation, so
            existing callers keep their previous behavior.

    Returns:
        A normalized URL string. If the input is empty or cannot be parsed,
        the stripped input is returned unchanged so callers can still flag it.
    """
    opts = options or DEFAULT_OPTIONS

    if raw_url is None:
        return ""
    url = str(raw_url).strip()
    if not url:
        return ""

    parts = urlsplit(url)

    # If there is no scheme or host, we cannot safely normalize. Return as-is.
    if not parts.scheme and not parts.netloc:
        return url

    scheme = parts.scheme.lower()
    if opts.force_https and scheme == "http":
        scheme = "https"

    netloc = parts.netloc.lower()

    if opts.keep_query:
        # Drop tracking parameters, keep the rest, and sort for stable comparison.
        kept_params = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMS
        ]
        kept_params.sort()
        query = urlencode(kept_params)
    else:
        query = ""

    path = _normalize_path(parts.path)

    # Fragment is intentionally dropped (empty string).
    return urlunsplit((scheme, netloc, path, query, ""))


def _normalize_path(path: str) -> str:
    """Normalize trailing slashes without changing meaning.

    A path that already looks like a file (its last segment contains a dot,
    e.g. "/sitemap.xml") keeps its form. Directory-style paths are given a
    single trailing slash. The root path stays "/".
    """
    if not path:
        return "/"
    if path == "/":
        return "/"

    last_segment = path.rstrip("/").rsplit("/", 1)[-1]
    looks_like_file = "." in last_segment

    if looks_like_file:
        return path.rstrip("/")
    # Collapse any duplicate trailing slashes into exactly one.
    return path.rstrip("/") + "/"


def path_only(raw_url: str) -> str:
    """Return just the normalized path for fallback path-only matching.

    Used only when the domain is known to be consistent across datasets and an
    exact normalized match has already failed.
    """
    parts = urlsplit(normalize_url(raw_url))
    return parts.path or "/"


def ga4_path_to_url(
    landing_path: str,
    site_domain: str,
    options: NormalizeOptions | None = None,
) -> str:
    """Convert a GA4 landing-page path into an absolute, normalized URL.

    GA4 typically reports landing pages as paths such as "/services/" rather
    than full URLs. Without a configured domain we cannot join GA4 rows to the
    other sources, so this returns an empty string in that case and the caller
    should flag the row as unmatched rather than guess.

    Args:
        landing_path: The GA4 landing-page value, e.g. "/services/" or a full
            URL if the property happens to store one.
        site_domain: Absolute origin like "https://example.com" (no trailing
            slash). If empty, no conversion is possible.
        options: Optional NormalizeOptions passed through to normalize_url.

    Returns:
        A normalized absolute URL, or "" if conversion is not possible.
    """
    if landing_path is None:
        return ""
    value = str(landing_path).strip()
    if not value:
        return ""

    # If GA4 already gave us an absolute URL, just normalize it.
    if value.startswith("http://") or value.startswith("https://"):
        return normalize_url(value, options)

    if not site_domain:
        return ""

    domain = site_domain.rstrip("/")
    if not value.startswith("/"):
        value = "/" + value
    return normalize_url(domain + value, options)


def normalize_url_record(
    raw_url: str,
    site_domain: str = "",
    options: NormalizeOptions | None = None,
) -> dict:
    """Normalize a URL and report how reliable the result is as a join key.

    This preserves the original input as source_url, returns the normalized
    form, and attaches a match-confidence judgement describing how the key was
    derived. The confidence here is about the normalization step only. Whether
    the key actually matches another dataset is decided later, at join time.

    Confidence levels:
        high   - Input was an absolute URL and normalized cleanly.
        medium - Input was a bare path that had to be combined with the
                 configured site domain to build an absolute URL.
        low    - Input was empty, was a bare path with no domain available, or
                 could not be parsed into a scheme and host.

    Args:
        raw_url: The raw URL or path from any source.
        site_domain: Absolute origin used to reconstruct bare paths. Optional.
        options: Optional NormalizeOptions controlling scheme and query rules.

    Returns:
        A dict with keys: source_url, normalized_url, match_confidence,
        match_method.
    """
    source_url = "" if raw_url is None else str(raw_url)
    value = source_url.strip()

    if not value:
        return {
            "source_url": source_url,
            "normalized_url": "",
            "match_confidence": "low",
            "match_method": "empty",
        }

    is_absolute = value.startswith("http://") or value.startswith("https://")
    if is_absolute:
        return {
            "source_url": source_url,
            "normalized_url": normalize_url(value, options),
            "match_confidence": "high",
            "match_method": "absolute",
        }

    if value.startswith("/"):
        if site_domain:
            return {
                "source_url": source_url,
                "normalized_url": ga4_path_to_url(value, site_domain, options),
                "match_confidence": "medium",
                "match_method": "path_reconstructed",
            }
        return {
            "source_url": source_url,
            "normalized_url": "",
            "match_confidence": "low",
            "match_method": "path_no_domain",
        }

    # Something like "example.com/page" with no scheme. urlsplit will not
    # recognize a host without a scheme, so this cannot be trusted as a key.
    parts = urlsplit(value)
    if parts.scheme and parts.netloc:
        return {
            "source_url": source_url,
            "normalized_url": normalize_url(value, options),
            "match_confidence": "high",
            "match_method": "absolute",
        }

    return {
        "source_url": source_url,
        "normalized_url": value,
        "match_confidence": "low",
        "match_method": "unparseable",
    }
