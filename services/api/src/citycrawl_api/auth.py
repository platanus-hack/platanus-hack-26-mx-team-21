"""Authentication dependencies.

- require_user: validates the caller's Supabase access token against Supabase Auth's
  /auth/v1/user endpoint. Supabase is never a trigger and never calls this API.
- require_operator: in addition, requires X-Operator-Key matching OPERATOR_API_KEY in
  constant time, so a browser user with a session cannot spend external API/storage budget.

Tests override these via FastAPI dependency_overrides; no live Supabase call is needed in
the normal suite."""
from __future__ import annotations
import hmac
from dataclasses import dataclass

import httpx
from fastapi import Depends, Header

from citycrawl_api.config import Settings, get_settings
from citycrawl_api.errors import ApiError, forbidden, unauthorized


@dataclass
class User:
    id: str
    email: str | None = None


async def _validate_supabase_token(token: str, settings: Settings) -> User:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise ApiError(503, "auth_unconfigured", "Authentication is not configured")
    url = settings.supabase_url.rstrip("/") + "/auth/v1/user"
    try:
        async with httpx.AsyncClient(timeout=settings.supabase_timeout_s) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}", "apikey": settings.supabase_anon_key},
            )
    except httpx.HTTPError:
        raise ApiError(503, "auth_unavailable", "Authentication service unavailable")
    if resp.status_code != 200:
        raise unauthorized("Invalid or expired session")
    body = resp.json()
    uid = body.get("id")
    if not uid:
        raise unauthorized("Invalid session")
    return User(id=uid, email=body.get("email"))


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized("Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise unauthorized("Missing bearer token")
    return token


async def require_user(authorization: str | None = Header(default=None)) -> User:
    settings = get_settings()
    return await _validate_supabase_token(_bearer(authorization), settings)


async def require_operator(
    user: User = Depends(require_user),
    x_operator_key: str | None = Header(default=None),
) -> User:
    """Requires a valid user token (via require_user) AND a matching operator key. Built on
    top of require_user so tests can override user validation and still exercise the
    operator-key gate in isolation."""
    expected = get_settings().operator_api_key
    if not expected:
        raise ApiError(503, "operator_unconfigured", "Operator access is not configured")
    if not x_operator_key or not hmac.compare_digest(x_operator_key, expected):
        raise forbidden("Invalid operator key")
    return user


async def require_service(x_operator_key: str | None = Header(default=None)) -> None:
    """Server-to-server guard: only the operator key, NO user token. For trusted internal
    callers (e.g. the WhatsApp controller) that have no browser session."""
    expected = get_settings().operator_api_key
    if not expected:
        raise ApiError(503, "operator_unconfigured", "Operator access is not configured")
    if not x_operator_key or not hmac.compare_digest(x_operator_key, expected):
        raise forbidden("Invalid operator key")
