"""
Where artefacts go: a directory.

There was an S3 client and a factory to choose between it and the filesystem. A
single machine has a filesystem, so that is all this is now.
"""

from __future__ import annotations

__all__ = ["get_storage"]


def get_storage():
    """The artefact store. A function so callers read the same as before."""
    from codelith.storage.local import FilesystemStorage

    return FilesystemStorage()
