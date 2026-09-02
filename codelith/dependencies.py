from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from codelith.core.security import decode_token
from codelith.db.session import AsyncSessionLocal
from codelith.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    from codelith.db.repositories.user_repo import UserRepository

    # `auto_error=False` means FastAPI hands over None rather than raising when the
    # header is absent, so this has to be checked. Without it every unauthenticated
    # request died on `None.credentials` and came back **500**, not 401 — which the
    # studio cannot act on: `api.ts` refreshes once on a 401 and then redirects to
    # sign-in, so an expired session surfaced as a server error instead of a login.
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials)
    except ValueError:
        # `from None`: a token that will not parse is a 401, and chaining the decode
        # error onto it says nothing a caller can act on.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = payload.get("sub")
    repo = UserRepository(db)
    user = await repo.get_by_id(int(user_id))  # type: ignore[arg-type]
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.role not in ("admin",):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def _role_checker(*roles: str):
    """Factory: returns a FastAPI dependency that enforces any of the given roles."""
    async def _check(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {' or '.join(roles)}",
            )
        return current_user
    return _check


async def get_current_user_or_token(
    db: Annotated[AsyncSession, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    token: str | None = Query(None),
) -> User:
    """Accepts JWT from Authorization header OR ?token= query param (needed for SSE EventSource)."""
    from codelith.db.repositories.user_repo import UserRepository

    raw = (credentials.credentials if credentials else None) or token
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_token(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user_id = payload.get("sub")
    user = await UserRepository(db).get_by_id(int(user_id))  # type: ignore[arg-type]
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserOrToken = Annotated[User, Depends(get_current_user_or_token)]
AdminUser = Annotated[User, Depends(get_current_admin)]

# Scoped role aliases — add "admin" first so admin can always do everything
ManagerUser = Annotated[User, Depends(_role_checker("admin", "manager"))]
ReviewerUser = Annotated[User, Depends(_role_checker("admin", "manager", "reviewer"))]
