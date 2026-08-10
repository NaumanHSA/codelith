from sqlalchemy.ext.asyncio import AsyncSession
from codelith.core.exceptions import AuthenticationError, ConflictError
from codelith.core.security import create_access_token, create_refresh_token, hash_password, verify_password, decode_token
from codelith.db.repositories.user_repo import UserRepository
from codelith.models.user import User
from codelith.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = UserRepository(db)
        self.db = db

    async def register(self, req: RegisterRequest) -> User:
        existing = await self.repo.get_by_email(req.email)
        if existing:
            raise ConflictError(f"Email '{req.email}' is already registered")

        user = await self.repo.create(
            email=req.email,
            password_hash=hash_password(req.password),
            full_name=req.full_name,
            role="user",
        )
        await self.db.commit()
        return user

    async def login(self, req: LoginRequest) -> TokenResponse:
        user = await self.repo.get_by_email(req.email)
        if not user or not user.password_hash:
            raise AuthenticationError("Invalid email or password")
        if not verify_password(req.password, user.password_hash):
            raise AuthenticationError("Invalid email or password")
        if not user.is_active:
            raise AuthenticationError("Account is disabled")

        return TokenResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )

    async def refresh(self, refresh_token: str) -> TokenResponse:
        try:
            payload = decode_token(refresh_token)
        except ValueError as e:
            raise AuthenticationError(str(e)) from e

        if payload.get("type") != "refresh":
            raise AuthenticationError("Invalid token type")

        user = await self.repo.get_by_id(int(payload["sub"]))
        if not user or not user.is_active:
            raise AuthenticationError("User not found or inactive")

        return TokenResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
        )
