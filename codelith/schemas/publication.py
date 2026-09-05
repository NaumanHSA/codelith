"""
What the studio sees of a published site.

The URL is assembled here rather than in the client, because the client should not
have to know that a slug becomes a path. Everything else is what the panel needs to
answer three questions at a glance: is it up, is it current, and what will happen if
I press Publish again.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PublicationBuildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    content_hash: str
    renderer: str
    renderer_version: str
    page_count: int
    file_count: int
    bytes_total: int
    commit_sha: str | None = None
    error: str | None = None
    verify_json: dict = Field(default_factory=dict)
    created_at: datetime
    finished_at: datetime | None = None


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    #: `live`, or the label of a frozen version.
    target: str
    slug: str
    renderer: str
    visibility: str
    status: str
    published_at: datetime | None = None
    unpublished_at: datetime | None = None
    current_build: PublicationBuildOut | None = None

    #: The path a reader opens. Relative, so it works whatever host the API is
    #: reached on: the studio joins it to the API origin, and a person sharing it
    #: copies whatever their browser then shows.
    url: str = ""

    #: The commit the newest reading of this project covers, and whether the
    #: published build was written from it. Two facts rather than a count: counting
    #: commits needs the repository, and the clone is gone once analysis is done.
    #: `None` on either means there is nothing to compare.
    latest_commit: str | None = None
    is_current: bool | None = None


class PublishRequest(BaseModel):
    #: `live` publishes the site as it stands. A version label publishes that
    #: snapshot, and gets its own address, so both stay up.
    target: str = "live"
    renderer: str | None = None
    #: Build even when nothing has changed. The studio sends this only after telling
    #: the reader that nothing has changed.
    force: bool = False


class PublishAccepted(BaseModel):
    """
    The answer to a publish request, which did not necessarily start one.

    `unchanged` is the interesting case: the site already serving is byte-for-byte
    what this request would have produced, so nothing was built and there is no job
    to watch.
    """

    unchanged: bool = False
    publication: PublicationOut
    job_id: int | None = None


class RendererOut(BaseModel):
    name: str
    version: str
    available: bool
    reason: str = ""


__all__ = [
    "PublicationBuildOut",
    "PublicationOut",
    "PublishAccepted",
    "PublishRequest",
    "RendererOut",
]
