from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.api.deps import get_current_user, is_admin
from app.core.database import get_db
from app.core.config import settings
from app.core.security import (verify_password, get_password_hash, create_access_token,
                               create_refresh_token, decode_token, password_fingerprint)
from app.models import User
from app.schemas.auth import Token, UserCreate, UserLogin

router = APIRouter()

REFRESH_COOKIE = "kandle_refresh"


def _set_refresh_cookie(response: Response, request: Request, user: User) -> None:
    """httpOnly — скрипт страницы (и XSS) его не прочитает; SameSite=Strict — чужой сайт не отправит;
    path=/api/auth — уходит только на вход/обновление/выход, не с каждым запросом."""
    response.set_cookie(
        REFRESH_COOKIE, create_refresh_token(user.username, user.hashed_password),
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, path="/api/auth",
        httponly=True, samesite="strict", secure=request.url.scheme == "https",
    )


def _session_response(response: Response, request: Request, user: User) -> dict:
    _set_refresh_cookie(response, request, user)
    return {"access_token": create_access_token(data={"sub": user.username}), "token_type": "bearer"}

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Изменения на signals./backtester., доступные любому вошедшему: расчёты, а не правка общих данных
USER_WRITE_PATHS = ("/api/run-backtest", "/api/download-data", "/api/current-price", "/api/optimize/start")


def proxy_access_allowed(user: User, method: str, uri: str) -> bool:
    """Чтение — любому вошедшему; изменение общих данных (стратегии сигналов, символы,
    история бэктестов) — только админу. Сервисы signals и backtester общие для всех
    пользователей, своих проверок у них нет."""
    if method.upper() in SAFE_METHODS:
        return True
    path = uri.split("?", 1)[0]
    if any(path == p or path.startswith(p + "/") for p in USER_WRITE_PATHS):
        return True
    return is_admin(user)


@router.get("/verify", status_code=204)
async def verify_for_proxy(request: Request, current_user: User = Depends(get_current_user)):
    """Для nginx auth_request перед signals./backtester.: 204 — пропустить, 401/403 — нет.
    Метод и путь исходного запроса nginx передаёт в X-Original-Method / X-Original-URI."""
    method = request.headers.get("X-Original-Method", "GET")
    uri = request.headers.get("X-Original-URI", "/")
    if not proxy_access_allowed(current_user, method, uri):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Изменение общих данных — только админу")
    return Response(status_code=204)


@router.post("/register", response_model=Token)
async def register(user_data: UserCreate, request: Request, response: Response,
                   db: AsyncSession = Depends(get_db)):
    """Register new user"""
    # Check if user exists
    result = await db.execute(select(User).where(User.username == user_data.username))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    # Create user
    hashed_password = get_password_hash(user_data.password)
    user = User(username=user_data.username, hashed_password=hashed_password)

    db.add(user)
    await db.commit()

    return _session_response(response, request, user)


@router.post("/login", response_model=Token)
async def login(user_data: UserLogin, request: Request, response: Response,
                db: AsyncSession = Depends(get_db)):
    """Login user"""
    # Get user
    result = await db.execute(select(User).where(User.username == user_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )

    return _session_response(response, request, user)


@router.post("/refresh", response_model=Token)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Новый access-токен по refresh-cookie; cookie продлевается (скользящие 30 дней).
    Пароль сменён после выдачи cookie — 401, нужен новый вход."""
    payload = decode_token(request.cookies.get(REFRESH_COOKIE, ""), "refresh")
    user = None
    if payload and payload.get("sub"):
        result = await db.execute(select(User).where(User.username == payload["sub"]))
        user = result.scalar_one_or_none()
    if not user or payload.get("pv") != password_fingerprint(user.hashed_password):
        expired = JSONResponse({"detail": "Session expired"}, status_code=status.HTTP_401_UNAUTHORIZED)
        expired.delete_cookie(REFRESH_COOKIE, path="/api/auth")
        return expired
    return _session_response(response, request, user)


@router.post("/logout", status_code=204)
async def logout():
    response = Response(status_code=204)
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    return response
