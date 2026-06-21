import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)
_BEARER_CREDENTIALS = Depends(_bearer)


@dataclass
class Principal:
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload: str, secret: str) -> str:
    signature = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(signature)


def create_token(username: str, role: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    body = {
        "sub": username,
        "role": role,
        "exp": int(time.time()) + settings.auth_token_ttl_minutes * 60,
    }
    payload = _b64encode(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    return f"{payload}.{_sign(payload, settings.auth_secret)}"


def decode_token(token: str, settings: Settings | None = None) -> Principal:
    settings = settings or get_settings()
    try:
        payload, signature = token.split(".", 1)
    except ValueError as exc:
        raise _credentials_error() from exc

    expected = _sign(payload, settings.auth_secret)
    if not hmac.compare_digest(expected, signature):
        raise _credentials_error()

    body = json.loads(_b64decode(payload))
    if int(body.get("exp", 0)) < int(time.time()):
        raise _credentials_error("Token expired.")
    return Principal(username=body["sub"], role=body.get("role", "user"))


def authenticate(username: str, password: str, settings: Settings | None = None) -> Principal:
    settings = settings or get_settings()
    record = settings.auth_users.get(username)
    if not record or not hmac.compare_digest(record["password"], password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    return Principal(username=username, role=record["role"])


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = _BEARER_CREDENTIALS,
) -> Principal | None:
    """Resolve the caller.

    Returns ``None`` when auth is disabled (unrestricted access), otherwise a
    validated :class:`Principal`, or raises 401 when the bearer token is missing
    or invalid.
    """
    settings = get_settings()
    if not settings.require_auth:
        return None
    if credentials is None or not credentials.credentials:
        raise _credentials_error("Authentication required.")
    return decode_token(credentials.credentials, settings)


def _credentials_error(detail: str = "Could not validate credentials.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
