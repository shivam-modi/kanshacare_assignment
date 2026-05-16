"""Domain-level exception types. Caught by middleware → mapped to HTTP status."""

from __future__ import annotations


class KanshaError(Exception):
    """Base for everything our code intentionally raises."""

    status_code: int = 500
    code: str = "internal_error"


class ValidationError(KanshaError):
    status_code = 400
    code = "validation_error"


class NotFoundError(KanshaError):
    status_code = 404
    code = "not_found"


class RateLimitedError(KanshaError):
    status_code = 429
    code = "rate_limited"


class UpstreamError(KanshaError):
    """A dependency we don't control is misbehaving (USGS, Telegram, geocoder)."""

    status_code = 502
    code = "upstream_error"


class ConflictError(KanshaError):
    status_code = 409
    code = "conflict"
