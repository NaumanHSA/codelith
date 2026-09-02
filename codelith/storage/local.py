"""
Artefact storage as a directory.

The same interface as the S3 client, backed by files under one root. Solo mode has no
bucket and no MinIO container; it has a folder, which is what "runs on your machine"
should mean.

Keys are treated as relative paths, exactly as they read: `exports/4/12/document.md`
becomes that path under the root. That makes the store browsable, which is worth
something on a single machine — the exports a person generated are findable in a file
manager rather than only through the application that wrote them.
"""

from __future__ import annotations

from pathlib import Path

from codelith.config import get_settings


class FilesystemStorage:
    """Artefacts under a directory, with the S3 client's interface."""

    def __init__(self, root: Path | str | None = None) -> None:
        settings = get_settings()
        self.root = Path(root or settings.LOCAL_STORAGE_DIR).expanduser().resolve()

    def _path(self, key: str) -> Path:
        """
        Resolve a key to a path, refusing anything that escapes the root.

        Keys are built from ids and slugs rather than user input today, but a store
        that can be talked out of its own directory by a `../` is one bad key away
        from writing anywhere the process can reach.
        """
        candidate = (self.root / key.lstrip("/")).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError(f"Key {key!r} escapes the storage root")
        return candidate

    async def upload_bytes(
        self, data: bytes, key: str, content_type: str = "text/plain"
    ) -> str:
        # `content_type` is accepted and ignored: a filesystem records it in the
        # extension, and the callers already put a meaningful one on every key.
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def upload_file(self, file_path: str, key: str) -> str:
        return await self.upload_bytes(Path(file_path).read_bytes(), key)

    async def download_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """
        A `file://` URL. Nothing expires, because nothing is being shared.

        The signature exists so callers do not branch. On a bucket the point of a
        presigned URL is handing a third party temporary access; on one machine there
        is no third party, and the honest answer is where the file is.
        """
        return self._path(key).as_uri()

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
