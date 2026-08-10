from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppException(Exception):
    def __init__(self, message: str, status_code: int = 400, detail: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


class NotFoundError(AppException):
    def __init__(self, resource: str, id: str | int):
        super().__init__(f"{resource} '{id}' not found", status_code=404)


class ConflictError(AppException):
    def __init__(self, message: str):
        super().__init__(message, status_code=409)


class AuthenticationError(AppException):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401)


class AuthorizationError(AppException):
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, status_code=403)


class ValidationError(AppException):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message, status_code=422, detail=detail or {})


class IngestionError(AppException):
    def __init__(self, message: str):
        super().__init__(message, status_code=500)


class LLMError(AppException):
    def __init__(self, message: str):
        super().__init__(message, status_code=502)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error"},
        )
