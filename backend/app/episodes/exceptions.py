"""Exceptions for the episodes domain."""

from app.core.exceptions import AppException


class EpisodesRepositoryError(AppException):
    """Raised when a repository call fails while serving an episodes request."""

    status_code = 500
    message = "Error while accessing episodes data"
