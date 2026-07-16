"""Shared constants for abackup core routines."""

# 1 MiB IO buffer: small enough for smooth byte-level progress, large enough
# for throughput. Used by both the zip and direct-copy methods so the chunk
# size stays consistent across backup strategies.
CHUNK = 1024 * 1024
