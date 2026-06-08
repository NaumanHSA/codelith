from fastapi import APIRouter
from app.dependencies import DbSession, CurrentUser
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(req: RegisterRequest, db: DbSession):
    user = await AuthService(db).register(req)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: DbSession):
    return await AuthService(db).login(req)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db: DbSession):
    return await AuthService(db).refresh(req.refresh_token)


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser):
    return current_user
