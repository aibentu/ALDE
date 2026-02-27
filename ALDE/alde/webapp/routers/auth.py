from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ..schemas import (
    LogoutRequest,
    OIDCCallbackRequest,
    OIDCStartRequest,
    OIDCStartResponse,
    RefreshTokenRequest,
    SSOLoginRequest,
    TenantRegisterRequest,
    TenantResponse,
    TokenResponse,
    UserResponse,
)
from ..repository import repo
from ..services import (
    build_oidc_authorize_url,
    oidc_callback_login,
    refresh_access_token,
    register_tenant,
    revoke_refresh_session,
    sso_login,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterTenantResponse(BaseModel):
    tenant: TenantResponse
    user: UserResponse
    token: TokenResponse


@router.post("/register-tenant", response_model=RegisterTenantResponse, status_code=status.HTTP_201_CREATED)
def register_tenant_endpoint(req: TenantRegisterRequest) -> RegisterTenantResponse:
    try:
        tenant, user, token = register_tenant(
            slug=req.slug.strip().lower(),
            name=req.name.strip(),
            admin_subject=f"bootstrap:{req.admin_email.strip().lower()}",
            admin_email=req.admin_email.strip().lower(),
            admin_display_name=req.admin_display_name.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return RegisterTenantResponse(
        tenant=TenantResponse(**tenant),
        user=UserResponse(**user),
        token=TokenResponse(**token),
    )


@router.post("/sso/login", response_model=TokenResponse)
def sso_login_endpoint(req: SSOLoginRequest) -> TokenResponse:
    # Provider is currently accepted for audit/extension points; subject is authoritative.
    _ = req.provider
    try:
        token = sso_login(
            tenant_slug=req.tenant_slug.strip().lower(),
            subject=req.subject.strip(),
            email=req.email.strip().lower(),
            display_name=req.display_name.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return TokenResponse(**token)


@router.post("/oidc/start", response_model=OIDCStartResponse)
def oidc_start(req: OIDCStartRequest) -> OIDCStartResponse:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    repo.save_oidc_state(tenant_slug=req.tenant_slug.strip().lower(), state=state, nonce=nonce)
    return OIDCStartResponse(
        authorization_url=build_oidc_authorize_url(
            tenant_slug=req.tenant_slug.strip().lower(),
            state=state,
            nonce=nonce,
        ),
        state=state,
    )


@router.post("/oidc/callback", response_model=TokenResponse)
def oidc_callback(req: OIDCCallbackRequest) -> TokenResponse:
    try:
        token = oidc_callback_login(
            tenant_slug=(req.tenant_slug or "").strip().lower(),
            state=req.state,
            code=req.code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OIDC exchange failed: {exc}") from exc

    return TokenResponse(**token)


@router.get("/oidc/callback", response_model=TokenResponse)
def oidc_callback_get(
    state: str = Query(...),
    code: str = Query(...),
    tenant_slug: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> TokenResponse:
    if error:
        detail = f"OIDC provider error: {error}"
        if error_description:
            detail = f"{detail} ({error_description})"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    try:
        token = oidc_callback_login(
            tenant_slug=(tenant_slug or "").strip().lower(),
            state=state,
            code=code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OIDC exchange failed: {exc}") from exc

    return TokenResponse(**token)


@router.post("/token/refresh", response_model=TokenResponse)
def refresh_token_endpoint(req: RefreshTokenRequest) -> TokenResponse:
    try:
        token = refresh_access_token(refresh_token=req.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(**token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_endpoint(req: LogoutRequest) -> None:
    revoke_refresh_session(refresh_token=req.refresh_token)
    return None
