"""
Where a published site lives, and what its address is.

Two rules, and both of them exist because of the same failure.

**A build directory is never renamed, moved or mutated.** It is created, filled, and
from then on only read or deleted. Making a build live is a database write, not a
filesystem operation. Windows refuses to rename a directory while any process holds a
file open inside it, so a staging-then-swap layout fails precisely when somebody is
reading the site, which is the only moment the swap matters.

**The address carries the secret.** `{project-slug}-{32 hex}` is the whole
capability: unguessable, shareable by copying, and revoked by minting another. No
query string to lose when a link is pasted into a chat window, and no session to
carry, because the people a site is shared with do not have one.
"""

from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path

from codelith.config import get_settings

#: Everything published sits under this, one directory per publication.
_ROOT = "published"

#: Half a UUID's worth of randomness. Enough that guessing is not a strategy, short
#: enough that the URL survives being pasted into a chat window unwrapped.
_TOKEN_BYTES = 16

_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


def storage_base() -> Path:
    """
    The artefact store itself.

    Build rows hold a path relative to this, so moving `CODELITH_HOME` moves every
    published site with it instead of orphaning the lot.
    """
    return Path(get_settings().STORAGE_DIR).expanduser().resolve()


def storage_root() -> Path:
    """The directory holding every published build."""
    return storage_base() / _ROOT


def build_key(publication_id: int, build_id: int) -> str:
    """
    A build's location, relative to the storage root.

    Stored on the row rather than an absolute path, so the store stays browsable and
    moving `CODELITH_HOME` does not invalidate every publication.
    """
    return f"{_ROOT}/{publication_id}/builds/{build_id}"


def build_dir(publication_id: int, build_id: int) -> Path:
    """Where a build's files go. Created by the builder, never moved afterwards."""
    return storage_root() / str(publication_id) / "builds" / str(build_id)


def publication_dir(publication_id: int) -> Path:
    """Everything ever built for one publication."""
    return storage_root() / str(publication_id)


def mint_slug(project_name: str) -> str:
    """
    A readable prefix so a person can tell two links apart, and a secret so nobody
    can find one they were not given.
    """
    stem = _SLUG_SAFE.sub("-", (project_name or "site").lower()).strip("-")[:48]
    return f"{stem or 'site'}-{secrets.token_hex(_TOKEN_BYTES)}"


def remove_tree(path: Path) -> bool:
    """
    Delete a build, and say whether it went.

    Best-effort on purpose. A reader with a file open stops Windows from unlinking
    it, and a publication that cannot delete an *old* build is not a publication that
    should fail: retention will pass this way again. The caller decides whether to
    care, and the only caller that does is the one deleting the build it just failed
    to write.
    """
    try:
        shutil.rmtree(path)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def resolve_within(root: Path, relative: str) -> Path | None:
    """
    A requested path inside a build, or `None` if it points anywhere else.

    The only defence the serving route has. `..`, an absolute path, a Windows drive
    letter, a backslash separator and a symlink out of the tree all have to fail
    here, so the check is on the *resolved* path rather than on the string: string
    inspection has to anticipate every encoding, and `resolve()` does not.

    **Backslashes are separators here on every platform.** `pathlib` only treats them
    that way on Windows; on Linux a backslash-separated path is one ordinary
    filename, so
    `root / that` stayed inside the root and the guard returned it. Harmless in the
    end, because no such file exists and the route answers 404, but the contract this
    function states was only being met on the platform it was written on, and the
    platform it actually runs on is the other one. Normalising first makes the answer
    the same in both places. It costs the ability to serve a file whose name really
    contains a backslash, which is not a thing a published documentation build has.
    """
    requested = relative.replace("\\", "/").lstrip("/")
    candidate = (root / requested).resolve()
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        return None
    return candidate


__all__ = [
    "build_dir",
    "build_key",
    "mint_slug",
    "publication_dir",
    "remove_tree",
    "resolve_within",
    "storage_base",
    "storage_root",
]
