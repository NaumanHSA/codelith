"""
Where artefacts go.

Server mode puts them in a bucket; solo mode puts them in a directory. Callers ask
for `get_storage()` and never learn which, because nothing they do with it differs —
the two implementations answer the same five methods.
"""

from __future__ import annotations

from typing import Protocol

from codelith.config import get_settings

__all__ = ["Storage", "get_storage"]


class Storage(Protocol):
    """What an artefact store has to be able to do."""

    async def upload_bytes(self, data: bytes, key: str, content_type: str = ...) -> str: ...

    async def upload_file(self, file_path: str, key: str) -> str: ...

    async def download_bytes(self, key: str) -> bytes: ...

    def presigned_url(self, key: str, expires_in: int = ...) -> str: ...

    async def delete(self, key: str) -> None: ...


def get_storage() -> Storage:
    """
    The store this installation writes to.

    Imported inside the function so that solo mode never imports boto3 and server
    mode never touches the local root — and so `codelith/storage/s3.py` remains the
    only module in the tree that names boto3 at all, which `test_storage_seams.py`
    enforces.
    """
    if get_settings().CODELITH_PROFILE == "solo":
        from codelith.storage.local import FilesystemStorage

        return FilesystemStorage()

    from codelith.storage.s3 import StorageClient

    return StorageClient()
