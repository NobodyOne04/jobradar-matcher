"""Prometheus metrics (jobradar ADR 0009), served at /metrics inside the compose network.
Label values stay bounded: route templates, status codes, model version numbers."""

from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "matcher_requests_total", "Requests by route template and status code.", ["route", "code"]
)
MATCH_DURATION = Histogram(
    "matcher_match_duration_seconds",
    "Time to score one /v1/match batch, by model version.",
    ["model_version"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
