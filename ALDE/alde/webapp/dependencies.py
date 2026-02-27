from __future__ import annotations

from fastapi import Header, HTTPException, status

from .security import Principal, decode_access_token


def get_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    kind, _, token = authorization.partition(" ")
    if kind.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    try:
        return decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
