import hmac

from fastapi import Header, HTTPException

from app.config import get_settings


async def require_key(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Aceita `X-API-Key: <key>` ou `Authorization: Bearer <key>` (Alertmanager)."""
    expected = get_settings().api_key
    if not expected:
        raise HTTPException(503, "API_KEY não configurada no servidor")
    supplied = x_api_key
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "unauthorized")
