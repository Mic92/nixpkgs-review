class NixpkgsReviewError(Exception):
    """Base class for exceptions in this module."""


class ArtifactExpiredError(NixpkgsReviewError):
    """Raised when GitHub artifacts have expired or been removed."""
