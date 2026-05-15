class ConfigError(Exception):
    """Raised when configuration or required environment variables are invalid."""


class GitHubAPIError(Exception):
    """Raised when GitHub API calls or git operations fail."""


class InstagramAPIError(Exception):
    """Raised when Instagram Graph API calls fail."""


class InstagramTokenError(InstagramAPIError):
    """Raised when an Instagram access token is expired or invalid."""


class InstagramPermissionError(InstagramAPIError):
    """Raised when the app lacks the required Instagram permissions."""


class InstagramRateLimitError(InstagramAPIError):
    """Raised when the Instagram API rate-limits the request."""
