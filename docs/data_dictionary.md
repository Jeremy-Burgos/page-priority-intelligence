# Data Dictionary

This document defines every field the tool reads from input CSVs and every column it
writes to the scored master report. It is the reference for what each value means, where
it comes from, and how it is used. If a column is missing from your export, the tool
treats it as absent rather than failing, and the affected score components fall back to
neutral or lower-confidence values.

Column-name matching is case-insensitive and ignores punctuation and spacing, so
`Avg. Position`, `avg_position`, and `Average Position` all map to the same field. If
your tool uses a header this tool does not recognize, rename the column to one of the
accepted names listed below.

## Input sources

### Screaming Frog (Internal: All, or HTML export)

Screaming Frog is the base crawl universe. The set of URLs in this file defines which
pages get scored. If a page is not in the crawl, it is not scored, even if it appears in
Search Console or analytics. Those non-crawl rows are captured separately as unmatched
rows rather than silently dropped.

| Field | Accepted headers | Type | Meaning and use |
|---|---|---|---|
| url | Address, URL | string | The page URL. Required. Normalized into `normalized_url` for joining. |
| status_code | Status Code | integer | HTTP response code. Drives technical risk. Non-200 codes (404, 5xx, redirects on indexable pages) raise risk sharply. |
| indexability | Indexability | string | Screaming Frog indexability label (Indexable, Non-Indexable). Used to detect pages excluded from search. |
| indexability_status | Indexability Status | string | Reason for non-indexability (Noindex, Canonicalised, Redirected). Used in technical risk. |
| title | Title 1, Title | string | Page title. Used to detect duplicate titles across the crawl. |
| word_count | Word Count | integer | Body word count. Low counts contribute to thin-content signals where present. |
| inlinks | Inlinks, Unique Inlinks | integer | Internal links pointing to the page. Low internal linking on a high-demand page is an internal link gap. |

### Google Search Console (Pages export, or Pages plus Queries)

Search Console is the demand and performance-versus-expectation source. Demand is measured
from impressions. Underperformance is measured by comparing actual click-through rate
against the expected rate for the page's ranking band.

| Field | Accepted headers | Type | Meaning and use |
|---|---|---|---|
| url | Page, Top pages, URL | string | The page URL. Required for the row to be usable. |
| gsc_clicks | Clicks | integer | Organic clicks in the period. Component of realized value. |
| gsc_impressions | Impressions | integer | Organic impressions in the period. Primary demand signal. |
| gsc_ctr | CTR | float | Click-through rate. Values above 1 are treated as percentages and divided by 100. Compared against expected CTR for the ranking band. |
| gsc_avg_position | Position, Avg. Position | float | Average ranking position. Determines the ranking band (1 to 3, 4 to 10, 11 to 20, 21 to 50, 51 plus). |

### GA4 (Landing page report, or Pages and screens)

GA4 supplies engagement and conversion signals. GA4 commonly exports a path
(`/category/widgets`) rather than a full URL. The tool reconstructs a full URL by
prefixing the configured site domain. If no site domain is configured and the export is
path-only, those rows cannot be joined and are reported as unmatched.

| Field | Accepted headers | Type | Meaning and use |
|---|---|---|---|
| url | Landing page, Page path, Page path and screen class, URL | string | Page path or URL. Combined with the site domain to build a joinable URL. |
| ga4_sessions | Sessions | integer | Sessions in the period. Engagement and realized-traffic signal. |
| ga4_conversions | Conversions, Key events | float | Conversions or key events. Primary business-value signal when present. |
| ga4_engagement_rate | Engagement rate | float | Engagement rate. Secondary engagement signal. |

### Backlinks (any backlink tool export at URL level)

The backlink export supplies external authority at the page level. Referring domains is
preferred over raw backlink counts because raw counts are easier to inflate and less
correlated with authority.

| Field | Accepted headers | Type | Meaning and use |
|---|---|---|---|
| url | URL, Target, Target URL, Page | string | The linked-to page. |
| referring_domains | Referring Domains, Ref domains | integer | Count of unique linking domains. Primary external authority signal. |
| backlinks | Backlinks, External Links | integer | Total inbound links. Secondary, lower-weight authority signal. |

### PageSpeed Insights (per-URL export or assembled CSV)

PageSpeed supplies Core Web Vitals. Field (real-user) data is preferred when present;
lab data is acceptable as a fallback. Thresholds follow Google's published good, needs
improvement, and poor bands.

| Field | Accepted headers | Type | Meaning and use |
|---|---|---|---|
| url | URL, Page | string | The measured page. |
| psi_lcp | LCP, Largest Contentful Paint | float (seconds) | Largest Contentful Paint. Good at or below 2.5s, poor above 4.0s. |
| psi_inp | INP, Interaction to Next Paint | float (milliseconds) | Interaction to Next Paint. Good at or below 200ms, poor above 500ms. |
| psi_cls | CLS, Cumulative Layout Shift | float (unitless) | Cumulative Layout Shift. Good at or below 0.10, poor above 0.25. |
| psi_performance_score | Performance, Performance Score | float (0 to 100) | Lighthouse performance score, used as a fallback severity signal. |

### URL Inspection (Search Console URL Inspection export)

URL Inspection supplies Google's indexing verdict and the canonical Google actually
selected. The tool compares the Google-selected canonical against the user-declared
canonical and derives a `canonical_match` flag. A mismatch is a meaningful technical
signal that Google is ignoring the declared canonical.

| Field | Accepted headers | Type | Meaning and use |
|---|---|---|---|
| url | URL, Inspected URL | string | The inspected page. |
| coverage_state | Coverage, Coverage State, Verdict | string | Indexing verdict (Indexed, Crawled not indexed, Discovered not indexed, Excluded). |
| google_canonical | Google-selected canonical, Google Canonical | string | The canonical Google chose. |
| user_canonical | User-declared canonical, User Canonical | string | The canonical declared on the page. |
| canonical_match | derived | boolean | True when normalized Google and user canonicals agree, False when they differ, null when either is missing. |

## Output: scored master report

These are the columns written to the downloadable master CSV, in order. Rows are sorted
by `priority_score` descending.

| Column | Type | Meaning |
|---|---|---|
| url | string | The crawled page URL. One row per crawled URL. |
| status_code | integer | HTTP status from the crawl. |
| indexability | string | Indexability label from the crawl. |
| gsc_clicks | integer | Organic clicks (joined from Search Console). |
| gsc_impressions | integer | Organic impressions (joined from Search Console). |
| gsc_ctr | float | Click-through rate as a fraction. |
| gsc_avg_position | float | Average ranking position. |
| ga4_sessions | integer | Sessions (joined from GA4). |
| ga4_conversions | float | Conversions or key events (joined from GA4). |
| referring_domains | integer | Unique referring domains (joined from backlinks). |
| inlinks | integer | Internal links to the page (from the crawl). |
| psi_lcp | float | Largest Contentful Paint in seconds. |
| psi_inp | float | Interaction to Next Paint in milliseconds. |
| psi_cls | float | Cumulative Layout Shift. |
| demand_score | float (0 to 1) | Search demand, driven mainly by impressions, log-scaled against the crawl. |
| underperformance_score | float (0 to 1) | Gap between actual CTR and expected CTR for the ranking band. |
| technical_risk_score | float (0 to 1) | Weighted technical issues: status code, indexability, canonical conflict, duplicate title, thin content. |
| authority_internal_link_gap_score | float (0 to 1) | Shortfall in external authority and internal links relative to the page's demand. |
| performance_risk_score | float (0 to 1) | Core Web Vitals severity. |
| decay_score | float (0 to 1) | Period-over-period decline. Fixed at 0 in this version because only a single period is ingested. |
| business_value_score | float (0 to 1) | Realized and assigned business value from conversions, sessions, and optional manual importance. |
| priority_score | float (0 to 100) | Weighted combination of the components above. Relative ranking signal, not an absolute grade. |
| recommendation_bucket | string | One of nine action buckets (see scoring_model.md). |
| primary_recommendation | string | Plain-language next action for the bucket. |
| confidence_score | string | High, Medium, or Low, based on how many sources contributed real data for the row. |

## Output: unmatched rows report

A second CSV captures rows from non-crawl sources (Search Console, GA4, backlinks,
PageSpeed, URL Inspection) whose normalized URL did not match any crawled page. Each row
carries an `unmatched_source` label identifying which source it came from. This report
exists so that data is never silently discarded. A large unmatched count usually means a
crawl scope problem, a domain or protocol mismatch, or GA4 path data without a configured
site domain.
