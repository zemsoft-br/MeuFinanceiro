"""Stable exception types that never include secret material."""


class SecurityError(Exception):
    """Base class for security primitive failures."""


class SecurityConfigurationError(SecurityError):
    """Raised when required security configuration is absent or unsafe."""


class KeyringError(SecurityConfigurationError):
    """Raised when a keyring cannot be parsed or validated."""


class KeyUnavailableError(SecurityError):
    """Raised when an envelope references a key that is not available."""


class EnvelopeError(SecurityError):
    """Raised when an encrypted envelope is malformed."""


class EnvelopeIntegrityError(EnvelopeError):
    """Raised when authenticated decryption fails."""


class PasswordHashError(SecurityError):
    """Raised when a password hash is malformed or cannot be processed."""
