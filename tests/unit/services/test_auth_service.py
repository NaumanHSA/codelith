import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.auth_service import AuthService
from app.core.exceptions import AuthenticationError, ConflictError
from app.schemas.auth import RegisterRequest, LoginRequest


@pytest.mark.asyncio
async def test_register_duplicate_email():
    db = AsyncMock()
    svc = AuthService(db)
    svc.repo = AsyncMock()
    svc.repo.get_by_email.return_value = MagicMock()  # user exists

    with pytest.raises(ConflictError):
        await svc.register(RegisterRequest(email="dup@test.com", password="password123"))


@pytest.mark.asyncio
async def test_login_wrong_password():
    from app.core.security import hash_password
    db = AsyncMock()
    svc = AuthService(db)
    svc.repo = AsyncMock()
    mock_user = MagicMock()
    mock_user.password_hash = hash_password("correctpass")
    mock_user.is_active = True
    svc.repo.get_by_email.return_value = mock_user

    with pytest.raises(AuthenticationError):
        await svc.login(LoginRequest(email="user@test.com", password="wrongpass"))
