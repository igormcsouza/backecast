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


class EpisodeNotFoundError(AppException):
    """Raised when an episode id doesn't exist, or (on the public routes)
    exists but isn't `status=published` — the public detail route
    deliberately can't distinguish "doesn't exist" from "not published yet"
    in its response, so admin-only content never leaks through a 403 that
    confirms an unpublished episode's existence."""

    status_code = 404
    message = "Episode not found"


class EpisodeNotEditableError(AppException):
    """Raised when a PATCH targets an episode that isn't `status=review` —
    metadata edits only make sense before publish; editing an already
    published (or still-processing) episode isn't supported by this MVP."""

    status_code = 409
    message = "Episode is not in review — metadata can only be edited pre-publish"


class EpisodeNotPublishableError(AppException):
    """Raised when the review -> published conditional write finds the
    episode isn't `status=review` anymore — a duplicate click of Publish,
    or an episode that's still processing."""

    status_code = 409
    message = "Episode is not in review — only a reviewed episode can be published"
