"""
Encrypting the secrets this application stores for you.

**What this is worth, exactly.** An API key kept in the database is a key sitting in a
file that gets copied — a backup, a bind-mounted volume, a `docker cp`, a support
bundle, the SQLite file somebody attaches to an issue. Encrypting it means that file
alone does not hand the key over. That is the whole claim.

**What it is not.** It is not protection from someone who has both the database and
`APP_SECRET_KEY`, because the key is derived from that secret and it has to be — the
application must be able to decrypt without anybody typing a passphrase at boot. Nor
does it help if `APP_SECRET_KEY` is left at its default, which is why
`missing_configuration` complains about that separately.

Keys can still be supplied by environment variable instead, and for a deployment where
secrets are managed elsewhere that remains the better answer. This exists so that the
*app-shaped* deployment — a container somebody runs, configured through its own
settings page — is not forced to keep its keys in plaintext.

Fernet, from `cryptography`, which is already a dependency by way of `python-jose`.
Authenticated, so a tampered value fails to decrypt rather than decrypting to rubbish.
"""

from __future__ import annotations

import base64
import hashlib

import structlog
from cryptography.fernet import Fernet, InvalidToken

from codelith.config import get_settings

logger = structlog.get_logger(__name__)

#: Distinguishes this use of `APP_SECRET_KEY` from any other. Without it, a secret
#: reused for signing and for encryption shares key material across two purposes.
_SALT = b"codelith.model-credentials.v1"


def _fernet() -> Fernet:
    """
    A key derived from `APP_SECRET_KEY`.

    Derived rather than stored so there is one secret to manage, and hashed rather
    than used raw because Fernet needs exactly 32 url-safe base64 bytes and
    `APP_SECRET_KEY` is whatever somebody typed.
    """
    secret = get_settings().APP_SECRET_KEY.encode("utf-8")
    digest = hashlib.sha256(_SALT + secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    """Ciphertext for storage. An empty value stays empty rather than becoming noise."""
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str:
    """
    Plaintext, or `""` when it cannot be recovered.

    Returns rather than raises on `InvalidToken`, because the realistic cause is
    `APP_SECRET_KEY` having changed — a redeploy with a fresh secret, a container
    without its env — and every stored key becoming unreadable at once. That should
    surface as "this endpoint needs its key again" on a settings page, not as a
    stack trace from inside whatever job happened to run first.
    """
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.warning(
            "credential_unreadable",
            hint="APP_SECRET_KEY has probably changed since this was stored",
        )
        return ""
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("credential_decrypt_failed", error=str(exc))
        return ""


def is_recoverable(value: str | None) -> bool:
    """Whether a stored secret can still be read, for the settings page to show."""
    return bool(value) and bool(decrypt(value))


__all__ = ["decrypt", "encrypt", "is_recoverable"]
