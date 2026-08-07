"""Module containing custom exception classes for the pyrail package."""


class RateLimitError(Exception):
    """Raised when the rate limit is exceeded."""

    pass


class InvalidRequestError(Exception):
    """Raised for invalid requests."""

    pass


class NotFoundError(Exception):
    """Raised when an endpoint is not found."""

    pass
