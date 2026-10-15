"""Module containing custom exception classes for the pyrail package."""


class PyRailError(Exception):
    """Base exception class for all pyrail exceptions."""


class RateLimitError(PyRailError):
    """Raised when the API rate limit is exceeded.

    This exception indicates that too many requests have been made to the API
    within a short time period. The client should wait before making new requests.
    """

    def __init__(self, message: str = "API rate limit exceeded") -> None:
        """Initialize the exception with a message."""
        super().__init__(message)


class InvalidRequestError(PyRailError):
    """Raised when the API request is invalid.

    This exception indicates that the request was malformed or contained
    invalid parameters that the API cannot process.
    """

    def __init__(self, message: str = "Invalid API request") -> None:
        """Initialize the exception with a message."""
        super().__init__(message)


class NotFoundError(PyRailError):
    """Raised when the requested resource is not found.

    This exception indicates that the requested station, train, or other
    resource does not exist or could not be found in the system.
    """

    def __init__(self, message: str = "Resource not found") -> None:
        """Initialize the exception with a message."""
        super().__init__(message)


class ApiUnavailableError(PyRailError):
    """Raised when the API could not be reached or kept failing after all retries.

    This exception indicates a network failure, a request timeout or a server error (HTTP 5xx)
    that persisted through every attempt. The request may succeed later.
    """

    def __init__(self, message: str = "API unavailable") -> None:
        """Initialize the exception with a message."""
        super().__init__(message)
