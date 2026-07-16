"""Typed exceptions for abackup."""

from __future__ import annotations


class ABackupError(Exception):
    """Base error for all abackup-specific failures."""


class ConfigError(ABackupError):
    """Raised when settings or jobs config is invalid or unreadable."""


class SourceNotFound(ABackupError):
    """Source path does not exist or is not a directory."""


class DestinationError(ABackupError):
    """Destination is invalid or not writable."""


class JobNotFound(ABackupError):
    """Requested job id does not exist."""


class JobCancelled(ABackupError):
    """Raised when a backup job is aborted via a cancellation signal."""
