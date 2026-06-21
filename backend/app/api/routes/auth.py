from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import Principal, authenticate, create_token, get_principal
from app.schemas.auth import LoginRequest, TokenResponse, UserInfo

router = APIRouter()
CURRENT_PRINCIPAL = Depends(get_principal)


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest) -> TokenResponse:
    principal = authenticate(request.username, request.password)
    token = create_token(principal.username, principal.role)
    return TokenResponse(
        access_token=token,
        username=principal.username,
        role=principal.role,
    )


@router.get("/me", response_model=UserInfo)
def me(principal: Principal | None = CURRENT_PRINCIPAL) -> UserInfo:
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication is disabled; no current user.",
        )
    return UserInfo(username=principal.username, role=principal.role)
