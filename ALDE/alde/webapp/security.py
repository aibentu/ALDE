from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    subject: str
    email: str
    role: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_access_token(*, tenant_id: str, user_id: str, subject: str, email: str, role: str) -> tuple[str, int]:
    exp = int(time.time()) + settings.token_ttl_minutes * 60
    payload = {
        "tid": tenant_id,
        "uid": user_id,
        "sub": subject,
        "email": email,
        "role": role,
        "exp": exp,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = _b64url(payload_bytes)
    sig = hmac.new(settings.token_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url(sig)}", exp


def decode_access_token(token: str) -> Principal:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Malformed token") from exc

    expected = hmac.new(settings.token_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64url_decode(sig)):
        raise ValueError("Invalid token signature")

    data = json.loads(_b64url_decode(body).decode("utf-8"))
    now = int(time.time())
    if int(data.get("exp", 0)) < now:
        raise ValueError("Token expired")

    return Principal(
        tenant_id=str(data["tid"]),
        user_id=str(data["uid"]),
        subject=str(data["sub"]),
        email=str(data["email"]),
        role=str(data["role"]),
    )


def issue_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
