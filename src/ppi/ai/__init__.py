"""Optional AI recommendation writer.

This layer is strictly optional. The scoring engine and the rule-based
recommendation writer work with no AI and no network. When an OpenAI or Claude
key is configured, this layer rewrites the recommendation prose from structured
facts only. It never calculates scores and never receives raw datasets. If the
provider is missing or fails for any reason, it falls back to the rule-based
recommendation so the tool always produces valid output.
"""
