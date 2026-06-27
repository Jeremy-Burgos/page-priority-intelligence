# Scoring Model

This document describes exactly how Page Priority Intelligence calculates a
priority score. The goal is not a generic SEO grade. The goal is a defensible
answer to one question: which pages should be worked on first, and why.

Code calculates every score. Nothing here depends on a language model.

## Main formula

```
Priority Score =
100 × (
    0.35 × SEO Opportunity
  + 0.20 × Technical Risk Opportunity
  + 0.15 × Authority/Internal Link Gap
  + 0.10 × Performance Risk Opportunity
  + 0.10 × Decay Risk
  + 0.10 × Business Value
)
```

The three opportunity terms are products, not standalone scores:

```
SEO Opportunity          = Demand Score × Underperformance Score
Technical Risk Opportunity = Demand Score × Technical Risk Score
Performance Risk Opportunity = Traffic Value Score × Performance Risk Score
```

The product design is deliberate. A technical problem on a page with no demand
is not urgent. A CTR gap on a page nobody sees is not an opportunity. Risk and
underperformance only convert into priority when there is demand or traffic
value behind them. This is what stops dead, low-value pages from dominating the
recommendations simply because they look bad on a raw average.

## Why medians, percentiles, and log scaling

SEO data is skewed. A single homepage can hold most of the backlinks. A single
article can hold most of the impressions. Comparing every page to the mean
flatters a few outliers and buries everything else.

The model therefore uses one normalization primitive for skewed positive
metrics (impressions, clicks, sessions, conversions, revenue, referring domains,
inlinks):

```
Normalized Metric = min( log1p(value) / log1p(P90_value), 1 )
```

A page at or above the 90th percentile scores 1.0. Everything below scales
smoothly. Missing or non-positive values score 0.0. Averages are still useful
for context in a report, but they are never used as the scoring baseline.

## Component scores

All component scores are bounded 0.0 to 1.0.

### Demand Score

```
Demand = 0.60 × Normalized Impressions
       + 0.20 × Normalized Query Count
       + 0.20 × Ranking Opportunity
```

Ranking Opportunity rewards pages that are visible and within reach:

| Average position | Score |
|---|---|
| 1 to 3 | 0.30 |
| 4 to 10 | 1.00 |
| 11 to 20 | 0.85 |
| 21 to 50 | 0.50 |
| 51+ | 0.15 |
| No data | 0.00 |

### Underperformance Score

```
Underperformance = 0.40 × CTR Gap
                 + 0.25 × Click Gap
                 + 0.20 × GA4 Session Gap
                 + 0.15 × Engagement Gap
```

CTR Gap is measured against the median CTR for the page's ranking band, never a
single sitewide CTR:

```
CTR Gap = max(0, Expected CTR - Actual CTR) / Expected CTR
```

where Expected CTR is the median CTR of pages in the same position band. If a
band has no data, the global median CTR is used; if the site has no CTR data at
all, a small floor keeps the calculation defined.

### Technical Risk Score

```
Technical Risk = 0.25 × Indexability problem
              + 0.20 × Status code problem
              + 0.15 × Canonical problem
              + 0.15 × Robots/Noindex problem
              + 0.10 × Metadata problem
              + 0.05 × Crawl depth problem
              + 0.10 × Content thinness problem
```

Issue severities applied within those dimensions:

| Issue | Severity |
|---|---|
| Non-200 status code | 1.00 |
| Non-indexable | 1.00 |
| Noindex on a page with impressions | 1.00 |
| Blocked by robots | 1.00 |
| Google-selected canonical differs from declared | 0.80 |
| Missing title | 0.60 |
| Duplicate title | 0.40 |
| Missing meta description | 0.30 |
| Missing H1 | 0.30 |
| Word count below 200 | 0.30 |
| Crawl depth greater than 4 | 0.30 |

### Authority/Internal Link Gap

```
Gap = 0.50 × Referring Domain Gap
    + 0.30 × Internal Link Gap
    + 0.20 × Crawl Depth Gap

Referring Domain Gap = 1 - Normalized Referring Domains
Internal Link Gap    = 1 - Normalized Inlinks
Crawl Depth Gap      = clamp( (crawl_depth - 1) / 5 , 0, 1 )
```

Referring domains are weighted above raw backlinks because they are the more
reliable authority signal.

### Performance Risk Score

```
Performance Risk = 0.35 × LCP Risk
                + 0.35 × INP Risk
                + 0.20 × CLS Risk
                + 0.10 × Lighthouse Risk
```

Risk for each Core Web Vital ramps linearly between Google's good and poor
thresholds:

| Metric | Good (risk 0) | Poor (risk 1) |
|---|---|---|
| LCP | 2.5 s | 4.0 s |
| INP | 200 ms | 500 ms |
| CLS | 0.10 | 0.25 |

Lighthouse Risk is `1 - (performance_score / 100)`.

### Decay Risk

```
Decay = 0.40 × Click decline
      + 0.30 × Impression decline
      + 0.20 × Session decline
      + 0.10 × Conversion decline
```

Each decline is the fractional drop from the previous period, floored at 0.
This requires current vs previous period columns. In the CSV-only MVP those
columns are usually absent, so Decay Risk is 0.0 until period data is supplied.

### Business Value

```
Business Value = 0.50 × Normalized Conversions
              + 0.30 × Normalized Revenue
              + 0.20 × Manual Strategic Importance
```

Manual Strategic Importance is an optional 0 to 1 value the user can attach per
URL:

| Value | Meaning |
|---|---|
| 1.00 | Money page, service page, lead-gen page |
| 0.75 | Important blog, tool, or product page |
| 0.50 | Supporting informational content |
| 0.25 | Low-priority informational page |
| 0.00 | Exclude, archive, or monitor only |

## Recommendation buckets

Each URL is assigned exactly one bucket using a priority-ordered rule set. Order
matters: a page that is both broken and underperforming is flagged Fix Now,
because the block prevents any other gain. Evaluation order:

1. Fix Now: serious technical blocker on a page with demand or business value.
2. Performance Fix: high Core Web Vitals risk on a page with traffic, conversions, or demand.
3. Quick Win: high impressions, position 4 to 20, and CTR below the band expectation.
4. Refresh/Expand: demand with weak content signals or weak engagement.
5. Protect: high business value, technically clean, low risk, not declining.
6. Authority Gap: demand with a thin external authority profile.
7. Internal Link Push: demand with weak internal links or excessive crawl depth.
8. Merge/Prune: low impressions, clicks, sessions, links, and weak content.
9. Monitor: default when no rule fires or data is insufficient.

Performance Fix is placed above Quick Win on purpose. A slow page in striking
distance should have its Core Web Vitals fixed before its title is rewritten,
because the speed problem suppresses any CTR gain. This is a triage order, not
the literal listing order of the buckets.

Quick Win keys off the CTR gap specifically (exposed as ctr_gap_score), not the
blended underperformance score, so a page with high clicks-to-sessions loss but
a healthy CTR is not mislabeled a Quick Win.

Authority Gap and Internal Link Push are evaluated against two separate
sub-gaps, not the single combined authority score. Authority Gap fires on a
high referring-domain gap (external authority). Internal Link Push fires on a
high internal-link gap (inlinks) or excessive crawl depth, when the
referring-domain gap is not itself high. Keeping them separate is what makes
both buckets reachable; the combined score alone cannot tell an external
authority problem apart from an internal linking problem.

Thresholds for these rules live as named constants in `src/ppi/scoring/buckets.py`
so they can be tuned without changing logic.

## Confidence

Each URL receives High, Medium, or Low confidence based on how many independent
sources actually backed that row, not just which files were uploaded.

- High: crawl, Search Console, and GA4 all present for the row, plus at least
  one of PageSpeed, URL Inspection, or backlinks.
- Medium: crawl and Search Console present for the row.
- Low: only one major source, or key metrics missing.

## Stated assumptions

These choices were defined by this implementation where the source spec was
directional rather than exact. They are listed here so the math stays
inspectable.

1. Traffic Value Score (used only in Performance Risk Opportunity) is
   `0.40 sessions + 0.30 clicks + 0.20 conversions + 0.10 revenue`, all
   log-normalized.
2. Click Gap is `max(0, normalized impressions - normalized clicks)`.
3. GA4 Session Gap is `max(0, normalized clicks - normalized sessions)` and is
   only applied when GA4 sessions exist for the row.
4. Engagement Gap is `1 - engagement_rate` where GA4 engagement rate exists.
5. PageSpeed units are assumed to be LCP in seconds, INP in milliseconds, CLS as
   a unitless ratio, and Lighthouse scores on a 0 to 100 scale.
6. CTR exported as a percentage (a value above 1) is converted to a fraction.

## What the score is not

The priority score is a relative ranking of effort, not a prediction. Absolute
values cluster in a band that depends on the site's data shape. Compare scores
to each other within one run, not across different sites or different exports.
This tool does not guarantee rankings, traffic, conversions, or indexing.
