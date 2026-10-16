"""Package initialization for pyrail."""

from importlib.metadata import PackageNotFoundError, version
import logging

from .exceptions import (
    ApiUnavailableError,
    InvalidRequestError,
    InvalidResponseError,
    NotFoundError,
    PyRailError,
    RateLimitError,
)
from .irail import iRail

logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    __version__ = version("pyrail")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = [
    "ApiUnavailableError",
    "InvalidRequestError",
    "InvalidResponseError",
    "NotFoundError",
    "PyRailError",
    "RateLimitError",
    "__version__",
    "iRail",
]
