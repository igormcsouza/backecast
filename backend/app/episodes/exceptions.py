"""Exceptions for the episodes domain."""

from app.core.exceptions import AppException


class EpisodesRepositoryError(AppException):
    """Raised when a repository call fails while serving an episodes request."""

    status_code = 500
    message = "Error while accessing episodes data"


class EpisodeAlreadyExistsError(AppException):
    """Raised when a create() conditional write finds the item already exists."""

    status_code = 409
    message = "Episode already exists"


class UnsupportedMediaTypeError(AppException):
    """Raised when the requested content type isn't an accepted audio format."""

    status_code = 415
    message = "Unsupported content type"
