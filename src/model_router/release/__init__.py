"""Explicit Phase 6 release loading, preflight, and activation API."""

from .activation import (
    ActivationBlocked,
    CredentialConfigurationError,
    activate,
    parse_application_credentials,
    preflight,
)
from .loader import LoadedRelease, ReleaseConfigurationError, load_release
from .schema import ActivationReport, PreflightReport, RuntimeEvidence

__all__ = [
    "ActivationBlocked",
    "ActivationReport",
    "CredentialConfigurationError",
    "LoadedRelease",
    "PreflightReport",
    "ReleaseConfigurationError",
    "RuntimeEvidence",
    "activate",
    "load_release",
    "parse_application_credentials",
    "preflight",
]
