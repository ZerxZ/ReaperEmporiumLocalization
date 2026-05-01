class LocalizationToolError(Exception):
    """Base exception for this helper project."""


class ConfigurationError(LocalizationToolError):
    """Raised when required local configuration is missing."""


class SafePathError(LocalizationToolError):
    """Raised when a filesystem operation would leave the expected root."""


__all__ = ["ConfigurationError", "LocalizationToolError", "SafePathError"]
